from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType


def load_generator(monkeypatch):
    scripts = ModuleType("scripts")
    update_wiki = ModuleType("scripts.update_wiki")
    update_wiki.build_inventory = lambda wiki_root: {"items": []}
    update_wiki.is_under_any = lambda path, roots: any(
        Path(path).resolve().is_relative_to(Path(root).resolve()) for root in roots
    )
    monkeypatch.setitem(sys.modules, "scripts", scripts)
    monkeypatch.setitem(sys.modules, "scripts.update_wiki", update_wiki)
    sys.modules.pop("llm_wiki_forge.resources.scripts.generate_module_wiki", None)
    return importlib.import_module("llm_wiki_forge.resources.scripts.generate_module_wiki")


def test_ios_static_discovery_scans_app_sources_and_xcode_surface(tmp_path, monkeypatch):
    generator = load_generator(monkeypatch)
    repo = tmp_path / "iOSTaiwanTaxi55688"
    (repo / "TaiwanTaxiClient.xcodeproj" / "xcshareddata" / "xcschemes").mkdir(parents=True)
    (repo / "TaiwanTaxiClient.xcodeproj" / "project.pbxproj").write_text("// !Xcode\n", encoding="utf-8")
    (repo / "TaiwanTaxiClient.xcodeproj" / "xcshareddata" / "xcschemes" / "TaiwanTaxiClient.xcscheme").write_text(
        "<Scheme />\n",
        encoding="utf-8",
    )
    (repo / "Config").mkdir()
    (repo / "Config" / "TaiwanTaxiClient_Debug.xcconfig").write_text("PRODUCT_NAME=Taxi\n", encoding="utf-8")
    app_delegate = repo / "TaiwanTaxiClient" / "Supporting Files" / "AppDelegate.swift"
    request_m = repo / "TaiwanTaxiClient" / "Website" / "WebApiRequest" / "ServiceStatementRequest.m"
    request_h = request_m.with_suffix(".h")
    test_file = repo / "TaiwanTaxiClientUnitTest" / "ServiceStatementTest.swift"
    vendor_header = repo / "TaiwanTaxiAds.xcframework" / "ios-arm64" / "TaiwanTaxiAds.framework" / "Headers" / "TaiwanTaxiAds-Swift.h"
    app_delegate.parent.mkdir(parents=True)
    request_m.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    vendor_header.parent.mkdir(parents=True)
    app_delegate.write_text(
        """
        import UIKit
        @main
        class AppDelegate: UIResponder, UIApplicationDelegate {
            func applicationDidFinishLaunching() {}
        }
        """,
        encoding="utf-8",
    )
    request_m.write_text(
        """
        @implementation ServiceStatementRequest
        - (NSString *)path { return @"AppApi/Service/Statement"; }
        @end
        """,
        encoding="utf-8",
    )
    request_h.write_text("@interface ServiceStatementRequest : NSObject\n@end\n", encoding="utf-8")
    test_file.write_text("class ServiceStatementTest {}\n", encoding="utf-8")
    vendor_header.write_text("@interface VendorHeader\n@end\n", encoding="utf-8")

    item = {
        "logicalName": "iOSTaiwanTaxi55688",
        "repo": "iOSTaiwanTaxi55688",
        "actualPath": str(repo),
        "resolvedPath": str(repo),
        "resolvedExcludePaths": [],
    }

    assert generator.detect_platform(repo) == "ios"
    files = generator.source_files_for_item(item, "ios")
    relative_files = {path.relative_to(repo).as_posix() for path in files}
    assert "TaiwanTaxiClient/Supporting Files/AppDelegate.swift" in relative_files
    assert "TaiwanTaxiClient/Website/WebApiRequest/ServiceStatementRequest.m" in relative_files
    assert "TaiwanTaxiClient/Website/WebApiRequest/ServiceStatementRequest.h" in relative_files
    assert "TaiwanTaxiClientUnitTest/ServiceStatementTest.swift" not in relative_files
    assert not any(".xcframework" in path for path in relative_files)

    entries, symbols = generator.scan_sources(item, "ios", files)
    assert any(entry["kind"] == "application_bootstrap" for entry in entries)
    assert any(entry["kind"] == "api_request" for entry in entries)
    assert any("AppApi/Service/Statement" in entry["route_surface"] for entry in entries)
    assert any(symbol["name"] == "AppDelegate" for symbol in symbols)

    surfaces = generator.discover_ios_surfaces(repo)
    assert surfaces["xcode_projects"] == ["TaiwanTaxiClient.xcodeproj"]
    assert surfaces["xcode_schemes"] == ["TaiwanTaxiClient.xcodeproj/xcshareddata/xcschemes/TaiwanTaxiClient.xcscheme"]
    assert surfaces["xcode_configs"] == ["Config/TaiwanTaxiClient_Debug.xcconfig"]
