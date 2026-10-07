import AppKit
import Foundation
import WebKit
import Darwin

private let servicePort: Int = {
    let configured = (Bundle.main.object(forInfoDictionaryKey: "CognesiaServerPort") as? NSNumber)?.intValue ?? 8794
    return (1...65535).contains(configured) ? configured : 8794
}()
private let serviceURL = URL(string: "http://127.0.0.1:\(servicePort)")!
private let logDirectory = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Logs/Cognesia", isDirectory: true)

private enum LaunchError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self { case .message(let text): return text }
    }
}

private enum Health {
    case ready, unavailable, occupied(String)
}

private enum DesktopCommand: String, CaseIterable {
    case newNote = "new-note", saveSession = "save-session", toggleNotes = "toggle-notes"
    case simulate, parameters, layout, settings, run, pause, resume, step, checkpoint, stop
    case stopAll = "stop-all"
}

@MainActor
final class CognesiaDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate,
    WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate, WKScriptMessageHandler, NSMenuItemValidation {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var statusView: NSView!
    private var statusTitle: NSTextField!
    private var statusDetail: NSTextField!
    private var spinner: NSProgressIndicator!
    private var retryButton: NSButton!
    private var connectTask: Task<Void, Never>?
    private var connectionGeneration = 0
    private var didLoadWorkspace = false
    private var desktopCommandEnabled: [DesktopCommand: Bool] = [:]
    private var desktopCommandChecked: [DesktopCommand: Bool] = [:]
    private var pendingEmergencyCommands = Set<UUID>()
    private var renderingDiagnosticRunning = false
    private struct ExportDestination { let temporary: URL; let final: URL }
    private var downloads: [ObjectIdentifier: ExportDestination] = [:]
    private let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 2
        configuration.timeoutIntervalForResource = 3
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        return URLSession(configuration: configuration)
    }()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        createMenus()
        createWindow()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        connect()
    }

    private func menuItem(_ title: String, _ action: Selector?, _ key: String = "", target: AnyObject? = nil) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = target
        return item
    }

    private func commandItem(_ title: String, _ command: DesktopCommand, _ key: String = "",
                             modifiers: NSEvent.ModifierFlags = [.command]) -> NSMenuItem {
        let item = menuItem(title, #selector(performDesktopCommand(_:)), key, target: self)
        item.representedObject = command.rawValue
        item.keyEquivalentModifierMask = modifiers
        return item
    }

    private func createMenus() {
        let main = NSMenu()
        let applicationItem = NSMenuItem()
        let applicationMenu = NSMenu(title: "Cognesia")
        applicationMenu.addItem(menuItem("About Cognesia", #selector(showAbout), target: self))
        applicationMenu.addItem(commandItem("Settings…", .settings, ","))
        applicationMenu.addItem(.separator())
        let services = NSMenu(title: "Services")
        let servicesItem = NSMenuItem(title: "Services", action: nil, keyEquivalent: "")
        servicesItem.submenu = services
        applicationMenu.addItem(servicesItem)
        NSApp.servicesMenu = services
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(menuItem("Hide Cognesia", #selector(NSApplication.hide(_:)), "h"))
        let hideOthers = menuItem("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        applicationMenu.addItem(hideOthers)
        applicationMenu.addItem(menuItem("Show All", #selector(NSApplication.unhideAllApplications(_:))))
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(menuItem("Quit Cognesia", #selector(NSApplication.terminate(_:)), "q"))
        applicationItem.submenu = applicationMenu
        main.addItem(applicationItem)

        let file = NSMenu(title: "File")
        file.addItem(commandItem("New Note", .newNote, "n"))
        file.addItem(commandItem("Save Session…", .saveSession, "s"))
        file.addItem(.separator())
        file.addItem(menuItem("Open in Browser", #selector(openInBrowser), target: self))
        file.addItem(menuItem("Show Project in Finder", #selector(showProject), target: self))
        file.addItem(menuItem("Show Logs", #selector(showLogs), target: self))
        file.addItem(.separator())
        file.addItem(menuItem("Close Window", #selector(NSWindow.performClose(_:)), "w"))
        addMenu(file, to: main)

        let edit = NSMenu(title: "Edit")
        edit.addItem(menuItem("Undo", Selector(("undo:")), "z"))
        let redo = menuItem("Redo", Selector(("redo:")), "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(redo)
        edit.addItem(.separator())
        for (title, selector, key) in [("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(menuItem(title, Selector(selector), key))
        }
        addMenu(edit, to: main)

        let view = NSMenu(title: "View")
        view.addItem(commandItem("Simulate", .simulate, "1"))
        view.addItem(commandItem("Parameters", .parameters, "2"))
        view.addItem(commandItem("Hide Notes", .toggleNotes, "n", modifiers: [.command, .shift]))
        view.addItem(.separator())
        view.addItem(commandItem("Layout…", .layout))
        view.addItem(commandItem("Settings…", .settings))
        view.addItem(.separator())
        view.addItem(menuItem("Reload Workspace", #selector(reloadWorkspace), "r", target: self))
        view.addItem(.separator())
        view.addItem(menuItem("Actual Size", #selector(resetZoom), "0", target: self))
        view.addItem(menuItem("Zoom In", #selector(zoomIn), "+", target: self))
        view.addItem(menuItem("Zoom Out", #selector(zoomOut), "-", target: self))
        view.addItem(.separator())
        let fullscreen = menuItem("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f")
        fullscreen.keyEquivalentModifierMask = [.control, .command]
        view.addItem(fullscreen)
        addMenu(view, to: main)

        let simulation = NSMenu(title: "Simulation")
        simulation.addItem(commandItem("Run Simulation", .run, "r", modifiers: [.command, .shift]))
        simulation.addItem(commandItem("Pause", .pause))
        simulation.addItem(commandItem("Resume", .resume))
        simulation.addItem(commandItem("Step", .step))
        simulation.addItem(commandItem("Save Checkpoint", .checkpoint))
        simulation.addItem(commandItem("Stop Simulation", .stop))
        simulation.addItem(.separator())
        simulation.addItem(commandItem("Stop All — Emergency", .stopAll, ".", modifiers: [.command, .option]))
        addMenu(simulation, to: main)

        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(menuItem("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"))
        windowMenu.addItem(menuItem("Zoom", #selector(NSWindow.performZoom(_:))))
        windowMenu.addItem(.separator())
        windowMenu.addItem(menuItem("Bring All to Front", #selector(NSApplication.arrangeInFront(_:))))
        addMenu(windowMenu, to: main)
        NSApp.windowsMenu = windowMenu

        let help = NSMenu(title: "Help")
        help.addItem(menuItem("Cognesia User Guide", #selector(showGuide), target: self))
        help.addItem(menuItem("Show Logs", #selector(showLogs), target: self))
        help.addItem(menuItem("Rendering Diagnostics…", #selector(showRenderingDiagnostics), target: self))
        addMenu(help, to: main)
        NSApp.helpMenu = help
        NSApp.mainMenu = main
    }

    private func addMenu(_ menu: NSMenu, to main: NSMenu) {
        let item = NSMenuItem(title: menu.title, action: nil, keyEquivalent: "")
        item.submenu = menu
        main.addItem(item)
    }

    private func createWindow() {
        let available = NSScreen.main?.visibleFrame.size ?? NSSize(width: 1440, height: 1000)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: min(1380, available.width - 40), height: min(900, available.height - 50)),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Cognesia"
        window.subtitle = "Whole-brain simulation"
        window.minSize = NSSize(width: 800, height: 580)
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.fullScreenPrimary]
        window.delegate = self
        if !window.setFrameUsingName("CognesiaMainWindow") { window.center() }
        window.setFrameAutosaveName("CognesiaMainWindow")
        window.appearance = NSAppearance(named: .darkAqua)
        guard let content = window.contentView else { return }

        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.preferences.isElementFullscreenEnabled = true
        configuration.userContentController.add(self, name: "cognesiaDesktop")
        // This main-frame script is limited to our loopback service. Navigation,
        // exports and external-link handling retain their existing policies.
        let desktopBootstrap = """
        (() => {
          if (location.protocol !== 'http:' || !['127.0.0.1','localhost'].includes(location.hostname) || location.port !== '\(servicePort)') return;
          Object.defineProperty(window, '__COGNESIA_DESKTOP__', {value:true});
          const mark = () => { if (!document.documentElement) return false; document.documentElement.classList.add('cognesia-desktop'); return true; };
          if (!mark()) { const observer = new MutationObserver(() => { if (mark()) observer.disconnect(); }); observer.observe(document, {childList:true}); }
          window.addEventListener('cognesia-desktop-state', event => {
            window.webkit.messageHandlers.cognesiaDesktop.postMessage(event.detail || {});
          });
          const errors = []; Object.defineProperty(window, '__cognesiaDesktopErrors', {value:errors});
          const remember = value => { errors.push(value); if (errors.length > 8) errors.shift(); };
          window.addEventListener('error', event => remember({message:String(event.message).slice(0,500),file:String(event.filename).split('?')[0],line:event.lineno,column:event.colno}));
          window.addEventListener('unhandledrejection', event => remember({message:String(event.reason?.message || event.reason).slice(0,500)}));
        })();
        """
        configuration.userContentController.addUserScript(WKUserScript(source: desktopBootstrap, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsLinkPreview = false
        webView.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            webView.topAnchor.constraint(equalTo: content.topAnchor),
            webView.bottomAnchor.constraint(equalTo: content.bottomAnchor)
        ])

        statusView = NSView()
        statusView.wantsLayer = true
        statusView.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        statusView.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(statusView)
        NSLayoutConstraint.activate([
            statusView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            statusView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            statusView.topAnchor.constraint(equalTo: content.topAnchor),
            statusView.bottomAnchor.constraint(equalTo: content.bottomAnchor)
        ])
        let icon = NSImageView(image: NSApp.applicationIconImage)
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.setContentHuggingPriority(.required, for: .vertical)
        icon.widthAnchor.constraint(equalToConstant: 72).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 72).isActive = true
        statusTitle = NSTextField(labelWithString: "Opening Cognesia")
        statusTitle.font = .systemFont(ofSize: 21, weight: .semibold)
        statusTitle.alignment = .center
        statusDetail = NSTextField(wrappingLabelWithString: "Connecting to the local simulator…")
        statusDetail.font = .systemFont(ofSize: 13)
        statusDetail.textColor = .secondaryLabelColor
        statusDetail.alignment = .center
        statusDetail.isSelectable = true
        spinner = NSProgressIndicator()
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.isDisplayedWhenStopped = false
        retryButton = NSButton(title: "Try Again", target: self, action: #selector(retryConnection))
        retryButton.bezelStyle = .rounded
        retryButton.keyEquivalent = "\r"
        let logs = NSButton(title: "Show Logs", target: self, action: #selector(showLogs))
        logs.bezelStyle = .rounded
        let buttons = NSStackView(views: [retryButton, logs])
        buttons.orientation = .horizontal
        buttons.spacing = 8
        let stack = NSStackView(views: [icon, statusTitle, statusDetail, spinner, buttons])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 15
        stack.translatesAutoresizingMaskIntoConstraints = false
        statusView.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: statusView.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: statusView.centerYAnchor, constant: -25),
            stack.widthAnchor.constraint(equalToConstant: 520),
            statusDetail.widthAnchor.constraint(equalTo: stack.widthAnchor)
        ])
    }

    private func showStatus(title: String, detail: String, loading: Bool) {
        statusTitle.stringValue = title
        statusDetail.stringValue = detail
        statusView.isHidden = false
        retryButton.isHidden = loading
        if loading { spinner.startAnimation(nil) } else { spinner.stopAnimation(nil) }
        window.subtitle = loading ? "Connecting to local simulator" : "Connection unavailable"
    }

    private func projectRoot() throws -> URL {
        guard let raw = Bundle.main.object(forInfoDictionaryKey: "CognesiaProjectRoot") as? String,
              !raw.isEmpty, raw.hasPrefix("/") else {
            throw LaunchError.message("The app is missing its project location. Rebuild the Cognesia app from the project folder to restore the link.")
        }
        let root = URL(fileURLWithPath: raw, isDirectory: true).standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: root.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            throw LaunchError.message("The Cognesia project could not be found at:\n\(root.path)\n\nIf you moved the project, rebuild the app from its new location.")
        }
        return root
    }

    private func health() async -> Health {
        do {
            let (data, response) = try await session.data(from: serviceURL.appendingPathComponent("api/health"))
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  json["service"] as? String == "flybrain-visual" else {
                return .occupied("Another service is answering on port \(servicePort). Cognesia has left it running. Close that service, then try again.")
            }
            return .ready
        } catch let error as URLError {
            if error.code == .cancelled { return .unavailable }
            if error.code == .timedOut {
                return .occupied("The local simulator is taking too long to respond. It may still be starting or busy. Wait a moment, then try again; an existing experiment has not been interrupted.")
            }
            return .unavailable
        } catch { return .unavailable }
    }

    private func connect() {
        connectTask?.cancel()
        connectionGeneration += 1
        let generation = connectionGeneration
        showStatus(title: "Opening Cognesia", detail: "Connecting to the local simulator…", loading: true)
        connectTask = Task { [weak self] in
            guard let self else { return }
            do {
                switch await health() {
                case .ready: break
                case .occupied(let message): throw LaunchError.message(message)
                case .unavailable:
                    try Task.checkCancellation()
                    let root = try projectRoot()
                    showStatus(title: "Starting the simulator", detail: "Preparing the local model. This can take a moment.\nYour saved experiments stay in the project folder.", loading: true)
                    let serverPID = try await startDetachedServer(root: root)
                    let deadline = Date().addingTimeInterval(120)
                    var ready = false
                    while Date() < deadline {
                        try Task.checkCancellation()
                        if case .ready = await health() { ready = true; break }
                        if let pid = serverPID, Darwin.kill(pid, 0) != 0 && errno == ESRCH {
                            let filename = servicePort == 8794 ? "server.log" : "server-\(servicePort).log"
                            throw LaunchError.message("The simulator stopped while starting. Open Show Logs to inspect \(filename), then try again after resolving the reported problem.\n\nProject: \(root.path)")
                        }
                        try await Task.sleep(nanoseconds: 500_000_000)
                    }
                    guard ready else {
                        throw LaunchError.message("The simulator has not become ready yet. It may still be preparing the model. Open the logs for details, or wait and try again.\n\nNo running server or experiment has been stopped.")
                    }
                }
                try Task.checkCancellation()
                guard generation == connectionGeneration else { return }
                showStatus(title: "Loading the workspace", detail: "Opening the local brain viewer…", loading: true)
                webView.load(URLRequest(url: serviceURL, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 30))
            } catch is CancellationError {
                // A newer explicit reconnect owns the status view.
            } catch {
                guard generation == connectionGeneration, !Task.isCancelled else { return }
                showStatus(title: "Unable to open Cognesia", detail: error.localizedDescription, loading: false)
            }
        }
    }

    private func startDetachedServer(root: URL) async throws -> Int32? {
        let python = root.appendingPathComponent(".venv/bin/python")
        let executable = root.appendingPathComponent(".venv/bin/flybrain")
        guard FileManager.default.isExecutableFile(atPath: python.path), FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw LaunchError.message("The Python environment is missing or incomplete in:\n\(root.path)/.venv\n\nFollow the local setup in README.md, then try again.")
        }
        try FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
        // Fixed code and argument arrays avoid shell expansion of project paths.
        // The short launcher exits; the actual server owns a new OS session.
        let script = #"""
import fcntl, json, os, pathlib, subprocess, sys, urllib.request
root, logs, port = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3])
suffix = '' if port == 8794 else '-' + str(port)
with (logs / 'launcher.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2) as response:
            if json.load(response).get('service') == 'flybrain-visual':
                print(json.dumps({'ready': True}))
                sys.exit(0)
            raise RuntimeError(f'Port {port} is already serving another application.')
    except OSError:
        pass
    import psutil
    identity = logs / ('server' + suffix + '.json')
    try:
        saved = json.loads(identity.read_text())
        previous = psutil.Process(saved['pid'])
        args = previous.cmdline()
        if (saved['root'] == str(root) and abs(previous.create_time() - saved['created']) < .01
            and str(root / '.venv/bin/flybrain') in args and '--port' in args and str(port) in args):
            print(json.dumps({'pid': previous.pid}))
            sys.exit(0)
    except (OSError, ValueError, KeyError, psutil.Error):
        pass
    environment = os.environ.copy()
    environment['PYTHONUNBUFFERED'] = '1'
    with (logs / ('server' + suffix + '.log')).open('ab', buffering=0) as stream:
        process = subprocess.Popen([str(root / '.venv/bin/flybrain'), '--root', str(root), 'view', '--port', str(port)],
            cwd=root, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True, env=environment)
    try:
        created = psutil.Process(process.pid).create_time()
        identity.write_text(json.dumps({'pid': process.pid, 'created': created, 'root': str(root)}))
    except (OSError, psutil.Error):
        pass
    print(json.dumps({'pid': process.pid}))
"""#
        let process = Process()
        process.executableURL = python
        process.arguments = ["-c", script, root.path, logDirectory.path, String(servicePort)]
        process.currentDirectoryURL = root
        process.standardInput = FileHandle.nullDevice
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        return try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Int32?, Error>) in
            process.terminationHandler = { process in
                let data = output.fileHandleForReading.readDataToEndOfFile()
                if process.terminationStatus == 0 {
                    let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                    continuation.resume(returning: (result?["pid"] as? NSNumber)?.int32Value)
                } else {
                    let detail = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "Unknown launcher error."
                    continuation.resume(throwing: LaunchError.message("The simulator could not start.\n\n\(detail)\n\nOpen Show Logs for server details."))
                }
            }
            do { try process.run() }
            catch { process.terminationHandler = nil; continuation.resume(throwing: error) }
        }
    }

    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        guard let raw = menuItem.representedObject as? String,
              let command = DesktopCommand(rawValue: raw) else { return true }
        if command == .toggleNotes {
            let visible = desktopCommandChecked[command] ?? true
            menuItem.title = visible ? "Hide Notes" : "Show Notes"
            menuItem.state = visible ? .on : .off
        }
        if command == .stopAll { return true }
        guard didLoadWorkspace, let url = webView?.url, isLocal(url) else { return false }
        return desktopCommandEnabled[command] ?? true
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "cognesiaDesktop", message.frameInfo.isMainFrame,
              let url = message.frameInfo.request.url, isLocal(url),
              let state = message.body as? [String: Any] else { return }
        if let enabled = state["enabled"] as? [String: Any] {
            for command in DesktopCommand.allCases {
                if let value = enabled[command.rawValue] as? Bool { desktopCommandEnabled[command] = value }
            }
        }
        if let checked = state["checked"] as? [String: Any] {
            for command in DesktopCommand.allCases {
                if let value = checked[command.rawValue] as? Bool { desktopCommandChecked[command] = value }
            }
        }
        if let ready = state["ready"] as? Bool { didLoadWorkspace = ready }
    }

    @objc private func performDesktopCommand(_ sender: NSMenuItem) {
        guard let raw = sender.representedObject as? String,
              let command = DesktopCommand(rawValue: raw) else { return }
        window.makeKeyAndOrderFront(nil)
        guard didLoadWorkspace, let url = webView.url, isLocal(url) else {
            if command == .stopAll { emergencyStopAll() }
            else { showAlert("Workspace is not ready", "Reconnect the workspace, then try this command again.") }
            return
        }
        if command != .stopAll && desktopCommandEnabled[command] == false {
            showAlert("Command unavailable", "This command is unavailable in the current simulation state.")
            return
        }
        // Only finite enum values reach JavaScript. preventDefault acknowledges
        // receipt; the frontend performs its current-state checks and feedback.
        let script = "!window.dispatchEvent(new CustomEvent('cognesia-desktop-command', {cancelable:true, detail:{action:'\(command.rawValue)'}}))"
        let emergencyID = command == .stopAll ? UUID() : nil
        if let emergencyID {
            pendingEmergencyCommands.insert(emergencyID)
            Task { [weak self] in
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                guard let self, pendingEmergencyCommands.remove(emergencyID) != nil else { return }
                emergencyStopAll()
            }
        }
        webView.evaluateJavaScript(script) { [weak self] result, error in
            guard let self else { return }
            if let emergencyID, pendingEmergencyCommands.remove(emergencyID) == nil { return }
            if error == nil, result as? Bool == true { return }
            if command == .stopAll { emergencyStopAll() }
            else { showAlert("Workspace command unavailable", error?.localizedDescription ?? "Reload the workspace to connect its native menu commands.") }
        }
    }

    private func emergencyStopAll() {
        // This bounded HTTP fallback remains usable when WebKit is loading or
        // unresponsive. It targets only the visualizer's managed simulations.
        Task { [weak self] in
            guard let self else { return }
            do {
                guard case .ready = await health() else {
                    throw LaunchError.message("The local simulator is not responding. Stop All could not be confirmed. Open Show Logs to inspect the service.")
                }
                var request = URLRequest(url: serviceURL.appendingPathComponent("api/stop-all"))
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.httpBody = Data("{}".utf8)
                let configuration = URLSessionConfiguration.ephemeral
                configuration.timeoutIntervalForRequest = 15
                configuration.timeoutIntervalForResource = 20
                let emergencySession = URLSession(configuration: configuration)
                defer { emergencySession.finishTasksAndInvalidate() }
                let (data, response) = try await emergencySession.data(for: request)
                guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                      let result = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let status = result["status"] as? String, ["stopped", "stopping"].contains(status) else {
                    throw LaunchError.message("The simulator did not confirm the stop request. Open Show Logs to inspect the service.")
                }
                window.subtitle = status == "stopped" ? "Managed simulations stopped" : "Stop requested"
                showAlert(status == "stopped" ? "Simulations stopped" : "Stop requested",
                          status == "stopped" ? "The local visualizer confirmed its managed simulations have stopped. Saved recordings are preserved." : "The local visualizer accepted the stop request and is finishing shutdown. Saved recordings are preserved; reload to inspect final status.")
            } catch { showAlert("Stop All could not be confirmed", error.localizedDescription) }
        }
    }

    @objc private func retryConnection() { connect() }
    @objc private func reloadWorkspace() { connect() }
    @objc private func openInBrowser() { NSWorkspace.shared.open(serviceURL) }
    @objc private func showLogs() {
        try? FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
        NSWorkspace.shared.open(logDirectory)
    }
    @objc private func showProject() {
        do { NSWorkspace.shared.open(try projectRoot()) }
        catch { showAlert("Project unavailable", error.localizedDescription) }
    }
    @objc private func showGuide() {
        do { NSWorkspace.shared.open(try projectRoot().appendingPathComponent("VISUAL_SIMULATOR.md")) }
        catch { showAlert("User guide unavailable", error.localizedDescription) }
    }
    @objc private func zoomIn() { webView.pageZoom = min(1.6, webView.pageZoom + 0.1) }
    @objc private func zoomOut() { webView.pageZoom = max(0.7, webView.pageZoom - 0.1) }
    @objc private func resetZoom() { webView.pageZoom = 1 }
    private func nativeRenderingSnapshot() -> [String: Any] {
        var ancestry: [[String: Any]] = []
        var view: NSView? = webView
        while let current = view {
            ancestry.append(["class": String(describing: type(of: current)), "hidden": current.isHidden,
                             "frame": NSStringFromRect(current.frame), "visibleRect": NSStringFromRect(current.visibleRect),
                             "alpha": current.alphaValue, "layerBacked": current.wantsLayer])
            view = current.superview
        }
        return ["appActive": NSApp.isActive, "appHidden": NSApp.isHidden,
                "windowVisible": window.isVisible, "windowKey": window.isKeyWindow,
                "windowMiniaturized": window.isMiniaturized, "windowOnActiveSpace": window.isOnActiveSpace,
                "windowOcclusionVisible": window.occlusionState.contains(.visible),
                "windowFrame": NSStringFromRect(window.frame), "statusHidden": statusView.isHidden,
                "webViewAttached": webView.window === window, "webViewLoading": webView.isLoading,
                "pageZoom": webView.pageZoom, "viewAncestry": ancestry,
                "system": ProcessInfo.processInfo.operatingSystemVersionString]
    }
    @objc private func showRenderingDiagnostics() {
        guard !renderingDiagnosticRunning else { return }
        guard let url = webView.url, isLocal(url) else {
            showAlert("Rendering diagnostics unavailable", "Load the local workspace before collecting its rendering state.")
            return
        }
        renderingDiagnosticRunning = true
        let before = nativeRenderingSnapshot()
        let begin = #"""
        (() => {
          const p = {raf:0,timers:0,started:performance.now(),rafID:null,timerID:null};
          window.__cognesiaRenderingProbe = p;
          const tick = () => { p.raf++; if (performance.now()-p.started < 2000) p.rafID=requestAnimationFrame(tick); };
          const timer = () => { p.timers++; if (performance.now()-p.started < 2000) p.timerID=setTimeout(timer,20); };
          p.rafID=requestAnimationFrame(tick); p.timerID=setTimeout(timer,20);
          return {visibility:document.visibilityState,hidden:document.hidden,focus:document.hasFocus(),ready:document.readyState};
        })()
        """#
        webView.evaluateJavaScript(begin) { [weak self] initial, error in
            guard let self else { return }
            if let error { renderingDiagnosticRunning=false; showAlert("Rendering diagnostics failed", error.localizedDescription); return }
            Task { [weak self] in
                try? await Task.sleep(nanoseconds: 2_200_000_000)
                guard let self else { return }
                let inspect = #"""
                (() => {
                  const p=window.__cognesiaRenderingProbe;
                  if(p){cancelAnimationFrame(p.rafID);clearTimeout(p.timerID);}
                  const dimensions = node => {
                    const b=node.getBoundingClientRect(),s=getComputedStyle(node);
                    return {width:b.width,height:b.height,x:b.x,y:b.y,display:s.display,visibility:s.visibility,opacity:s.opacity};
                  };
                  const canvases=[...document.querySelectorAll('#brain-canvas canvas,.fly-body-viewport canvas')].map(canvas=>{
                    let gl=null,glError=null;try{gl=canvas.getContext('webgl2')||canvas.getContext('webgl');}catch(e){glError=String(e);}
                    return {parent:canvas.parentElement.id||canvas.parentElement.className,bitmap:[canvas.width,canvas.height],box:dimensions(canvas),parentBox:dimensions(canvas.parentElement),renderState:canvas.dataset.renderState||null,lastDrawMs:canvas.dataset.lastDrawMs||null,glError,gl:gl?{lost:gl.isContextLost(),buffer:[gl.drawingBufferWidth,gl.drawingBufferHeight],version:gl.getParameter(gl.VERSION),renderer:gl.getParameter(gl.RENDERER),attributes:gl.getContextAttributes()}:null};
                  });
                  const grid=document.querySelector('.dock-primary-grid'),style=grid&&getComputedStyle(grid);
                  let rendering=null;try{rendering=window.cognesiaRenderingDiagnostics?.()||null;}catch(e){rendering={error:String(e)};}
                  const result={visibility:document.visibilityState,hidden:document.hidden,focus:document.hasFocus(),ready:document.readyState,viewport:[innerWidth,innerHeight],pixelRatio:devicePixelRatio,
                    probe:p?{raf:p.raf,timers:p.timers,elapsedMs:performance.now()-p.started}:null,canvases,errors:window.__cognesiaDesktopErrors||[],rendering,
                    grid:grid?{box:dimensions(grid),height:style.getPropertyValue('--overview-height'),left:style.getPropertyValue('--editing-left'),sequence:style.getPropertyValue('--editing-sequence')}:null};
                  delete window.__cognesiaRenderingProbe;return result;
                })()
                """#
                defer { renderingDiagnosticRunning = false }
                do {
                        let result = try await webView.evaluateJavaScript(inspect)
                        let report: [String: Any] = ["capturedAt": ISO8601DateFormatter().string(from: Date()),
                            "nativeBefore": before, "nativeAfter": nativeRenderingSnapshot(),
                            "pageBefore": initial ?? NSNull(), "pageAfter": result ?? NSNull()]
                        let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
                        try FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
                        let destination = logDirectory.appendingPathComponent("rendering-diagnostics.json")
                        try data.write(to: destination, options: .atomic)
                        let page=result as? [String: Any], probe=page?["probe"] as? [String: Any]
                        showAlert("Rendering diagnostics saved", "Animation frames: \(probe?["raf"] ?? "unknown") · timer callbacks: \(probe?["timers"] ?? "unknown")\nPage visibility: \(page?["visibility"] ?? "unknown")\n\n\(destination.path)")
                } catch { showAlert("Rendering diagnostics failed", error.localizedDescription) }
            }
        }
    }
    @objc private func showAbout() {
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: "Cognesia", .applicationIcon: NSApp.applicationIconImage as Any,
            .credits: NSAttributedString(string: "A local scientific workbench for the FlyWire whole-brain model.\n\nExperimental model: stability validation remains failed.\nQuitting this app leaves the local simulator and any active experiment running.", attributes: [.font: NSFont.systemFont(ofSize: 12)])
        ])
    }
    private func showAlert(_ title: String, _ detail: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = detail
        alert.alertStyle = .informational
        alert.addButton(withTitle: "OK")
        if window.isVisible { alert.beginSheetModal(for: window) } else { alert.runModal() }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        if !didLoadWorkspace && connectTask == nil { connect() }
        return true
    }
    func applicationWillTerminate(_ notification: Notification) {
        connectTask?.cancel()
        // Deliberately do not signal the detached simulator or its experiment.
    }

    private func isLocal(_ url: URL) -> Bool {
        url.scheme == "http" && ["127.0.0.1", "localhost"].contains(url.host ?? "") && url.port == servicePort
    }
    private func openExternal(_ url: URL) {
        if ["http", "https", "mailto"].contains(url.scheme?.lowercased() ?? "") { NSWorkspace.shared.open(url) }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if navigationAction.shouldPerformDownload && (isLocal(url) || url.scheme == "blob" || url.scheme == "data") {
            decisionHandler(.download)
        } else if isLocal(url) && navigationAction.targetFrame == nil {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        } else if isLocal(url) || url.absoluteString == "about:blank" {
            decisionHandler(.allow)
        } else {
            if navigationAction.navigationType == .linkActivated { openExternal(url) }
            decisionHandler(.cancel)
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(navigationResponse.canShowMIMEType ? .allow : .download)
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = navigationAction.request.url else { return nil }
        if isLocal(url) { NSWorkspace.shared.open(url) } else { openExternal(url) }
        return nil
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let url = webView.url, isLocal(url) else { return }
        didLoadWorkspace = true
        connectTask = nil
        statusView.isHidden = true
        spinner.stopAnimation(nil)
        window.subtitle = "Whole-brain simulation · local"
        window.makeFirstResponder(webView)
    }
    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        didLoadWorkspace = false
        desktopCommandEnabled.removeAll()
        desktopCommandChecked.removeAll()
    }
    private func navigationFailed(_ error: Error) {
        if (error as NSError).code == NSURLErrorCancelled { return }
        didLoadWorkspace = false
        showStatus(title: "Connection interrupted", detail: "The local workspace could not be loaded. Try again to reconnect.\n\n\(error.localizedDescription)", loading: false)
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { navigationFailed(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { navigationFailed(error) }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        didLoadWorkspace = false
        showStatus(title: "The viewer needs to reload", detail: "The graphics process stopped. Your saved experiments and the local simulator are separate from this window. Try again to reopen the viewer.", loading: false)
    }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert(); alert.messageText = "Cognesia"; alert.informativeText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert(); alert.messageText = "Cognesia"; alert.informativeText = message
        alert.addButton(withTitle: "OK"); alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.title = "Export from Cognesia"
        panel.nameFieldStringValue = (suggestedFilename as NSString).lastPathComponent
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { [weak self] result in
            guard result == .OK, let url = panel.url else { completionHandler(nil); return }
            // Download alongside the destination, then replace only after success.
            // A failed export must not destroy an existing user file.
            let temporary = url.deletingLastPathComponent().appendingPathComponent(".cognesia-\(UUID().uuidString).download")
            self?.downloads[ObjectIdentifier(download)] = ExportDestination(temporary: temporary, final: url)
            completionHandler(temporary)
        }
    }
    func downloadDidFinish(_ download: WKDownload) {
        guard let destination = downloads.removeValue(forKey: ObjectIdentifier(download)) else { return }
        do {
            if FileManager.default.fileExists(atPath: destination.final.path) {
                _ = try FileManager.default.replaceItemAt(destination.final, withItemAt: destination.temporary)
            } else {
                try FileManager.default.moveItem(at: destination.temporary, to: destination.final)
            }
            NSWorkspace.shared.activateFileViewerSelecting([destination.final])
        } catch {
            showAlert("Could not finish export", "The completed download is preserved at:\n\(destination.temporary.path)\n\n\(error.localizedDescription)")
        }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        if let destination = downloads.removeValue(forKey: ObjectIdentifier(download)) {
            try? FileManager.default.removeItem(at: destination.temporary)
        }
        if (error as NSError).code != NSURLErrorCancelled { showAlert("Export failed", error.localizedDescription) }
    }
}

@main
struct CognesiaMain {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = CognesiaDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
