import sys


def main() -> None:
    from backend.app.runtime import main as runtime_main

    runtime_main()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reload":
        from scripts.dev_reload import main as reload_main

        raise SystemExit(reload_main(sys.argv[2:]))

    main()
