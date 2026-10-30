"""Small deployment-controller tests using synthetic metadata only."""

import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("staging_manage", Path("deploy/manage.py"))
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


def config():
    environment = {
        "PRIVATE_STAGING": "true",
        "STAGING_INVITE_EPOCH": "b5b2d7b5-0b59-41c5-9de0-fad66fa44d41",
        "AI_ENABLED": "false",
        "REGISTRATION_ENABLED": "false",
        "PAYMENT_PROVIDER": "disabled",
        "ENABLE_LIVE_PAYMENTS": "false",
        "ENABLE_TRIAL_CREDITS": "false",
        "DEEPGRAM_API_KEY": "",
        "GEMINI_API_KEY": "",
        "GOOGLE_CLIENT_ID": "",
        "GOOGLE_CLIENT_SECRET": "",
        "GOOGLE_REDIRECT_URI": "",
        "EMAIL_MODE": "disabled",
        "MEDIA_ALLOWED_IMPORT_HOSTS": "[]",
    }
    services = {
        name: {
            "image": "fixture@sha256:" + "0" * 64,
            "environment": environment.copy(),
            "networks": {"data": {}},
        }
        for name in [
            "api",
            "worker-ai",
            "worker-render",
            "maintenance",
            "migrate",
            "proxy",
            "backup",
        ]
    }
    services["proxy"]["volumes"] = [
        {
            "source": "/fixture/nginx.private-staging.conf",
            "target": "/etc/nginx/nginx.conf",
            "read_only": True,
        }
    ]
    return {"services": services, "networks": {"data": {"internal": True}, "egress": {}}}


def test_closed_profile_accepted_without_execution():
    manage.validate_private_config(config())


def youtube_config():
    value = config()
    worker = value["services"]["worker-ai"]
    worker["networks"] = {name: {} for name in ["data", "queue", "egress"]}
    value["networks"]["queue"] = {"internal": True}
    worker["dns"] = ["1.1.1.1", "9.9.9.9"]
    worker["environment"].update(
        LINK_PROXY_URL="socks5://127.0.0.1:40000",
        LINK_EXTRACTOR_ARGS="youtube:player_client=mweb;fetch_pot=always",
    )
    value["services"]["link-proxy"] = {
        "image": value["services"]["api"]["image"],
        "network_mode": "service:worker-ai",
        "command": ["python", "-m", "zoclip.ops.link_proxy"],
        "user": "10001:10001",
        "read_only": True,
        "volumes": [
            {
                "type": "bind",
                "source": "/run/zoclip-link",
                "target": "/run/zoclip-link",
                "read_only": True,
                "bind": {"create_host_path": False},
            }
        ],
    }
    return value


def test_youtube_requires_explicit_opt_in():
    with pytest.raises(RuntimeError, match="networks must be internal"):
        manage.validate_private_config(youtube_config())
    manage.validate_private_config(youtube_config(), youtube_import=True)


@pytest.mark.parametrize("kind", ["api_egress", "public_proxy", "secrets", "mount", "dns"])
def test_youtube_cannot_reopen_other_private_boundaries(kind):
    value = youtube_config()
    if kind == "api_egress":
        value["services"]["api"]["networks"]["egress"] = {}
    elif kind == "public_proxy":
        value["services"]["link-proxy"]["ports"] = [{"host_ip": "0.0.0.0"}]
    elif kind == "secrets":
        value["services"]["link-proxy"]["secrets"] = ["runtime_database_url"]
    elif kind == "mount":
        value["services"]["link-proxy"]["volumes"][0]["source"] = "/"
    else:
        value["services"]["worker-ai"]["dns"] = ["127.0.0.1"]
    with pytest.raises(RuntimeError):
        manage.validate_private_config(value, youtube_import=True)


@pytest.mark.parametrize("name", ["api", "worker-ai", "worker-render", "maintenance", "migrate"])
@pytest.mark.parametrize(
    "key,value",
    [
        ("AI_ENABLED", "true"),
        ("REGISTRATION_ENABLED", "true"),
        ("GEMINI_API_KEY", "fixture-key"),
        ("PAYMENT_PROVIDER", "mock"),
    ],
)
def test_any_reopened_service_rejected(name, key, value):
    value_config = config()
    value_config["services"][name]["environment"][key] = value
    with pytest.raises(RuntimeError, match="remain closed"):
        manage.validate_private_config(value_config)


@pytest.mark.parametrize("kind", ["egress", "mutable_image", "wrong_proxy", "missing_epoch"])
def test_deployment_boundary_rejected(kind):
    value_config = copy.deepcopy(config())
    if kind == "egress":
        value_config["services"]["worker-ai"]["networks"]["egress"] = {}
    elif kind == "mutable_image":
        value_config["services"]["proxy"]["image"] = "fixture:latest"
    elif kind == "missing_epoch":
        value_config["services"]["api"]["environment"].pop("STAGING_INVITE_EPOCH")
    else:
        value_config["services"]["proxy"]["volumes"][0]["source"] = "/fixture/nginx.conf"
    with pytest.raises(RuntimeError):
        manage.validate_private_config(value_config)
