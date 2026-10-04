import sys
import habit_tracker
import gui


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--gui":
        gui.main()
    else:
        habit_tracker.main()


if __name__ == "__main__":
    main()
