import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class ProjectCleanupContractTest(unittest.TestCase):
    def test_legacy_business_files_are_removed(self):
        self.assertFalse((ROOT / "main.py").exists())
        self.assertFalse((ROOT / "shop_bot.py").exists())
        self.assertFalse((ROOT / "recovery.py").exists())

    def test_tracked_text_has_no_legacy_branding_or_shop_flow(self):
        legacy_terms = [
            "百龙霸业",
            "BaiLong",
            "BaiLongHelper",
            "AndroidScriptOrchestrator",
            "安卓脚本编排群控工具",
            "神秘商店",
            "扫货",
            "自动购买",
            "购买逻辑",
            "python main.py",
        ]
        allowed = {
            ".git",
            ".venv",
            "__pycache__",
            "dist",
            ".omo",
            "Daily",
            "Scripts",
            "Workflows",
        }
        text_suffixes = {".py", ".bat", ".md", ".txt", ".json", ".yml", ".yaml", ""}

        offenders = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if path.name == Path(__file__).name:
                continue
            relative_path = path.relative_to(ROOT)
            if any(part in allowed for part in relative_path.parts):
                continue
            if path.suffix.lower() not in text_suffixes:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            for term in legacy_terms:
                if term in content:
                    offenders.append(f"{path.relative_to(ROOT)}: {term}")

        self.assertEqual([], offenders)

    def test_project_files_use_official_project_name(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        build_script = (ROOT / "build.bat").read_text(encoding="utf-8")

        self.assertIn("镜界自动化", readme)
        self.assertIn("镜界自动化", build_script)
        self.assertIn("MirrorAutomation.exe", build_script)

if __name__ == "__main__":
    unittest.main()
