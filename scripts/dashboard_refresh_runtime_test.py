#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import dashboard_build  # noqa: E402


NODE_HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(process.argv[2], "utf8");
const RealDate = Date;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function makeNode(id) {
  return {
    id,
    tagName: "DIV",
    textContent: "",
    className: "",
    value: "",
    hidden: false,
    style: { display: "" },
    listeners: {},
    isContentEditable: false,
    addEventListener(type, fn) {
      if (!this.listeners[type]) this.listeners[type] = [];
      this.listeners[type].push(fn);
    },
    dispatch(type) {
      const handlers = this.listeners[type] || [];
      handlers.forEach((fn) =>
        fn({
          target: this,
          preventDefault() {},
          key: "",
        }),
      );
    },
    focus() {},
    select() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    scrollIntoView() {},
    classList: {
      add() {},
      remove() {},
      toggle() {},
      contains() { return false; },
    },
  };
}

function createStorage() {
  const data = new Map();
  return {
    getItem(key) {
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      data.set(key, String(value));
    },
    removeItem(key) {
      data.delete(key);
    },
  };
}

function bootDashboard(attrs) {
  const mergedAttrs = Object.assign(
    {
      "data-generated-at": "2026-03-05T00:00:00Z",
      "data-project-status": "in_progress",
      "data-monitor-status": "running",
      "data-monitor-cleanup-status": "none",
    },
    attrs || {},
  );

  let nowMs = RealDate.parse(mergedAttrs["data-generated-at"]) + 1000;
  function FakeDate(...args) {
    if (!(this instanceof FakeDate)) {
      return args.length ? RealDate(...args) : RealDate(nowMs);
    }
    return args.length ? new RealDate(...args) : new RealDate(nowMs);
  }
  FakeDate.now = () => nowMs;
  FakeDate.parse = RealDate.parse;
  FakeDate.UTC = RealDate.UTC;
  FakeDate.prototype = RealDate.prototype;

  const localStorage = createStorage();
  const sessionStorage = createStorage();
  const replaceCalls = [];
  const eventSources = [];
  let intervalFn = null;
  const windowListeners = {};
  const documentListeners = {};

  const ids = [
    "twRefreshToggle",
    "twRefreshNow",
    "twRefreshCountdown",
    "twRefreshStatus",
    "twStaleBadge",
    "twDataAge",
    "twQuery",
    "twQueueBody",
    "twQueueTable",
    "twCollapseAll",
    "twExpandAll",
    "twVisibleJobs",
    "twAtRiskJobs",
    "twActiveJobs",
  ];
  const elements = {};
  ids.forEach((id) => {
    elements[id] = makeNode(id);
  });
  elements.twQuery.tagName = "INPUT";
  elements.twQueueBody.tagName = "TBODY";
  elements.twQueueTable.tagName = "TABLE";
  elements.twRefreshToggle.tagName = "BUTTON";
  elements.twRefreshNow.tagName = "BUTTON";
  elements.twStaleBadge.style.display = "none";

  class FakeEventSource {
    constructor(url) {
      this.url = url;
      this.closed = false;
      this.onopen = null;
      this.onerror = null;
      this.onmessage = null;
      eventSources.push(this);
    }
    close() {
      this.closed = true;
    }
  }

  const document = {
    documentElement: {
      getAttribute(name) {
        return mergedAttrs[name] || "";
      },
      setAttribute(name, value) {
        mergedAttrs[name] = String(value);
      },
    },
    activeElement: null,
    getElementById(id) {
      return elements[id] || null;
    },
    querySelectorAll() {
      return [];
    },
    querySelector() {
      return null;
    },
    addEventListener(type, fn) {
      documentListeners[type] = fn;
    },
  };

  const windowObj = {
    document,
    location: {
      protocol: "http:",
      href: "http://127.0.0.1:43111/",
      replace(url) {
        replaceCalls.push(url);
        this.href = url;
      },
    },
    localStorage,
    sessionStorage,
    EventSource: FakeEventSource,
    scrollY: 0,
    scrollTo() {},
    setInterval(fn) {
      intervalFn = fn;
      return 1;
    },
    clearInterval() {},
    setTimeout() {
      return 1;
    },
    clearTimeout() {},
    addEventListener(type, fn) {
      windowListeners[type] = fn;
    },
  };
  windowObj.window = windowObj;
  windowObj.self = windowObj;
  windowObj.globalThis = windowObj;

  const context = {
    window: windowObj,
    document,
    console,
    EventSource: FakeEventSource,
    Date: FakeDate,
    JSON,
    Math,
    Array,
    String,
    Number,
    Boolean,
    Object,
    RegExp,
    parseInt,
    isNaN,
    setInterval: windowObj.setInterval,
    clearInterval: windowObj.clearInterval,
    setTimeout: windowObj.setTimeout,
    clearTimeout: windowObj.clearTimeout,
    localStorage,
    sessionStorage,
  };
  context.globalThis = context.window;
  context.self = context.window;

  vm.runInNewContext(source, context, { timeout: 1000 });

  return {
    elements,
    eventSources,
    replaceCalls,
    advance(ms) {
      nowMs += ms;
    },
    tick() {
      if (intervalFn) intervalFn();
    },
  };
}

function expectText(node, expected, label) {
  assert(node && node.textContent === expected, label + ": expected " + expected + ", got " + (node ? node.textContent : "<missing>"));
}

function runActiveToOfflineScenario() {
  const app = bootDashboard({
    "data-project-status": "in_progress",
    "data-monitor-status": "running",
  });
  assert(app.eventSources.length === 1, "expected initial EventSource for active dashboard");
  app.eventSources[0].onopen();
  expectText(app.elements.twRefreshStatus, "LIVE", "active dashboard should reach LIVE");

  app.eventSources[0].onerror();
  app.tick();
  expectText(app.elements.twRefreshStatus, "OFFLINE", "live feed loss should switch to OFFLINE");
  expectText(app.elements.twRefreshCountdown, "feed lost", "offline dashboard should show feed lost countdown text");

  app.advance(6000);
  app.tick();
  assert(app.replaceCalls.length === 0, "offline dashboard should not keep reloading");

  app.elements.twRefreshNow.dispatch("click");
  assert(app.replaceCalls.length === 1, "Refresh now should stay active while offline");
}

function runTerminalFrozenScenario() {
  const app = bootDashboard({
    "data-project-status": "cancelled",
    "data-monitor-status": "terminal",
    "data-monitor-cleanup-status": "pruned",
  });
  assert(app.eventSources.length === 0, "terminal snapshot should not start EventSource");
  app.tick();
  expectText(app.elements.twRefreshStatus, "FROZEN", "terminal dashboard should start frozen");
  expectText(app.elements.twRefreshCountdown, "frozen", "terminal dashboard should show frozen countdown text");

  app.elements.twRefreshToggle.dispatch("click");
  expectText(app.elements.twRefreshStatus, "ON", "resume from frozen should re-arm auto-refresh");
}

function runOfflineResumeScenario() {
  const app = bootDashboard({
    "data-project-status": "in_progress",
    "data-monitor-status": "running",
  });
  app.eventSources[0].onopen();
  app.eventSources[0].onerror();
  app.tick();
  expectText(app.elements.twRefreshStatus, "OFFLINE", "setup should reach OFFLINE before resume");

  app.elements.twRefreshToggle.dispatch("click");
  expectText(app.elements.twRefreshStatus, "ON", "resume from offline should enter ON reconnect window");
  assert(app.eventSources.length >= 2, "resume from offline should attempt a new EventSource");

  app.eventSources[1].onerror();
  app.tick();
  expectText(app.elements.twRefreshStatus, "ON", "offline probe should stay armed until timeout");

  app.advance(6000);
  app.tick();
  expectText(app.elements.twRefreshStatus, "OFFLINE", "offline probe should fail closed back to OFFLINE");
  assert(app.replaceCalls.length === 0, "offline resume should not restart endless reload churn");
}

runActiveToOfflineScenario();
runTerminalFrozenScenario();
runOfflineResumeScenario();
console.log("DASHBOARD REFRESH RUNTIME TEST PASSED");
"""


def main() -> None:
    node = shutil.which("node")
    if not node:
        print("DASHBOARD REFRESH RUNTIME TEST SKIPPED (node unavailable)")
        return

    with tempfile.TemporaryDirectory(prefix="theworkshop-dashboard-refresh-runtime-") as td:
        temp_dir = Path(td).resolve()
        js_path = temp_dir / "dashboard-runtime.js"
        harness_path = temp_dir / "dashboard-runtime-harness.js"
        js_path.write_text(dashboard_build._render_dashboard_js(), encoding="utf-8")
        harness_path.write_text(NODE_HARNESS, encoding="utf-8")

        proc = subprocess.run([node, str(harness_path), str(js_path)], text=True, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(
                "Dashboard runtime harness failed:\n"
                f"  exit={proc.returncode}\n"
                f"  stdout:\n{proc.stdout}\n"
                f"  stderr:\n{proc.stderr}\n"
            )

    print(proc.stdout.strip() or "DASHBOARD REFRESH RUNTIME TEST PASSED")


if __name__ == "__main__":
    main()
