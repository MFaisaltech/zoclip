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
