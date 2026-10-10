"""Local simulator-only API -> AI -> Linux RQ -> actual MP4 -> edit/rerender gate."""

from ai_smoke import main

if __name__ == "__main__":
    main(rendering=True)
