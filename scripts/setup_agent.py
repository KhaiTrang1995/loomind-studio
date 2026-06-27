import os
import shutil

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(script_dir, ".."))

    source_rules = os.path.join(root_dir, "docs", "ai-assistant-instructions.md")

    if not os.path.exists(source_rules):
        print(f"Error: Source rules file not found at {source_rules}")
        return

    print("Setting up AI Agent configuration files...")

    # Target files for common AI agents
    targets = [
        os.path.join(root_dir, ".cursorrules"),
        os.path.join(root_dir, ".clinerules"),
        os.path.join(root_dir, ".windsurfrules"),
        os.path.join(root_dir, ".github", "copilot-instructions.md")
    ]

    for target in targets:
        target_dir = os.path.dirname(target)
        os.makedirs(target_dir, exist_ok=True)

        try:
            shutil.copy2(source_rules, target)
            rel_path = os.path.relpath(target, root_dir)
            print(f"  [SUCCESS] Copied rules to: {rel_path}")
        except Exception as e:
            print(f"  [ERROR] Failed to copy to {target}: {e}")

    print("\nSetup complete! Your AI assistants (Cursor, Cline, Windsurf, Copilot) will now automatically read these instructions and connect to the Experience Engine.")

if __name__ == "__main__":
    main()
