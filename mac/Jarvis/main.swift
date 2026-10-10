// Jarvis for macOS: the dashboard in its own window, with the microphone, no browser needed.
//
// What it does:
// - Asks the Jarvis command line for the local dashboard link (`jarvis app --url`).
// - If Jarvis is not running yet, starts it in the background (`jarvis app --no-browser`) and
//   stops it again when this app quits. A Jarvis started elsewhere (terminal) is left running.
// - Shows the dashboard in a WKWebView. Only http://127.0.0.1 / localhost pages load inside
//   the window; any other link opens in the default browser.
// - Grants the page's microphone request only for the local dashboard. macOS itself asks once
//   ("Jarvis would like to access the microphone"), using NSMicrophoneUsageDescription.
//
// Build: scripts/build_mac_app.sh (swiftc, no Xcode project, no third-party code). The build
// writes the repository folder and the shell PATH into Info.plist (JarvisRepo, JarvisPath),
// because apps started from the Dock get a minimal PATH and Jarvis needs the `claude` CLI.

import AppKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?          // the Jarvis we started (nil when it was already running)
    var dashboardURL: URL?
    let info = Bundle.main.infoDictionary ?? [:]

    var repo: String { info["JarvisRepo"] as? String ?? "" }
    var jarvisBin: String { repo + "/.venv/bin/jarvis" }

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()             // keeps theme, name and settings between launches
        config.mediaTypesRequiringUserActionForPlayback = []
        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = false
        web.setValue(false, forKey: "drawsBackground")   // no white flash before the dark page paints

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 920),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "Jarvis"
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(red: 0.04, green: 0.067, blue: 0.125, alpha: 1)  // #0a1120
        window.minSize = NSSize(width: 760, height: 560)
        window.contentView = web
        window.center()
        window.setFrameAutosaveName("JarvisMainWindow")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        showMessage("Starting Jarvis…", detail: "")
        DispatchQueue.global(qos: .userInitiated).async { self.start() }
    }

    // MARK: start or attach

    func start() {
        guard FileManager.default.isExecutableFile(atPath: jarvisBin) else {
            return fail("Jarvis is not set up in \(repo).", detail: "Run scripts/setup.sh in the Jarvis folder, then build the app again.")
        }
        guard let link = runJarvis(["app", "--url"]), let url = URL(string: link) else {
            return fail("Could not read the dashboard link.", detail: "Run `jarvis app --url` in a terminal to see why.")
        }
        dashboardURL = url
        if !isUp(url) {
            startServer()
            var waited = 0.0
            while !isUp(url) && waited < 45 {
                Thread.sleep(forTimeInterval: 0.5)
                waited += 0.5
                if let s = server, !s.isRunning {
                    return fail("Jarvis stopped while starting.", detail: "See data/app.log in the Jarvis folder.")
                }
            }
            if !isUp(url) { return fail("Jarvis did not start in time.", detail: "See data/app.log in the Jarvis folder.") }
        }
        DispatchQueue.main.async { self.web.load(URLRequest(url: url)) }
    }

    func environment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        if let path = info["JarvisPath"] as? String, !path.isEmpty { env["PATH"] = path }
        env["PYTHONUNBUFFERED"] = "1"
        return env
    }

    /// Runs the Jarvis CLI and returns its last output line.
    func runJarvis(_ args: [String]) -> String? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: jarvisBin)
        p.arguments = args
        p.currentDirectoryURL = URL(fileURLWithPath: repo)
        p.environment = environment()
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        p.waitUntilExit()
        let text = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        guard p.terminationStatus == 0 else { return nil }
        return text.split(separator: "\n").last.map(String.init)
    }

    func startServer() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: jarvisBin)
        p.arguments = ["app", "--no-browser"]
        p.currentDirectoryURL = URL(fileURLWithPath: repo)
        p.environment = environment()
        let logURL = URL(fileURLWithPath: repo + "/data/app.log")
        try? FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let log = try? FileHandle(forWritingTo: logURL) {
            log.seekToEndOfFile()
            p.standardOutput = log
            p.standardError = log
        }
        do { try p.run(); server = p } catch {
            fail("Could not start Jarvis.", detail: error.localizedDescription)
        }
    }

    /// The dashboard answers on its root page (no token needed for the static page).
    func isUp(_ url: URL) -> Bool {
        var comps = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        comps.fragment = nil
        comps.path = "/"
        var req = URLRequest(url: comps.url!, timeoutInterval: 1.5)
        req.httpMethod = "GET"
        let done = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            ok = (resp as? HTTPURLResponse)?.statusCode == 200
            done.signal()
        }.resume()
        _ = done.wait(timeout: .now() + 2)
        return ok
    }

    // MARK: pages shown by the app itself

    func showMessage(_ title: String, detail: String) {
        let html = """
        <html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
        background:#0a1120;color:#e7edf7;font-family:-apple-system,system-ui;text-align:center">
        <div><div style="width:84px;height:84px;margin:0 auto 20px;border-radius:50%;
        box-shadow:0 0 0 4px #3b82f6,0 0 30px 6px rgba(59,130,246,.55);display:flex;align-items:center;
        justify-content:center;font-size:34px;font-weight:800">J</div>
        <div style="font-size:22px;font-weight:700">\(title)</div>
        <div style="color:#9fb0c9;margin-top:8px;max-width:520px">\(detail)</div></div></body></html>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    func fail(_ title: String, detail: String) {
        DispatchQueue.main.async { self.showMessage(title, detail: detail) }
    }

    // MARK: navigation and microphone

    func isLocal(_ url: URL?) -> Bool {
        guard let host = url?.host else { return url?.scheme == "about" }
        return ["127.0.0.1", "localhost", "::1"].contains(host)
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = action.request.url
        if isLocal(url) || url?.scheme == "about" || url?.scheme == "data" {
            decisionHandler(.allow)
        } else {
            if let u = url { NSWorkspace.shared.open(u) }   // outside links go to the default browser
            decisionHandler(.cancel)
        }
    }

    // target=_blank links
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = action.request.url {
            if isLocal(u) { webView.load(action.request) } else { NSWorkspace.shared.open(u) }
        }
        return nil
    }

    // The page asks for the microphone: allowed only for the local dashboard.
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                 decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        let local = ["127.0.0.1", "localhost", "::1"].contains(origin.host)
        decisionHandler(local && type == .microphone ? .grant : .deny)
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.runModal()
        completionHandler()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        showMessage("The dashboard did not load.", detail: "Press ⌘R to try again. \(error.localizedDescription)")
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showMessage("Jarvis is not answering.", detail: "Press ⌘R to try again. \(error.localizedDescription)")
    }

    // MARK: menu and quitting

    @objc func reload() {
        if let u = dashboardURL {
            DispatchQueue.global(qos: .userInitiated).async {
                if !self.isUp(u) && self.server == nil { self.startServer() }
                DispatchQueue.main.async { self.web.load(URLRequest(url: u)) }
            }
        } else {
            DispatchQueue.global(qos: .userInitiated).async { self.start() }
        }
    }

    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Jarvis", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Jarvis", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit Jarvis", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Edit")    // makes ⌘C / ⌘V / ⌘A work in the page's text boxes
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        let viewItem = NSMenuItem()
        let view = NSMenu(title: "View")
        view.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r")
        view.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        viewItem.submenu = view
        main.addItem(viewItem)

        let winItem = NSMenuItem()
        let win = NSMenu(title: "Window")
        win.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        winItem.submenu = win
        main.addItem(winItem)
        NSApp.mainMenu = main
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        guard let s = server, s.isRunning else { return }
        s.interrupt()                      // SIGINT: Jarvis shuts down cleanly (like Ctrl+C)
        let deadline = Date().addingTimeInterval(8)
        while s.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
        if s.isRunning { s.terminate() }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
