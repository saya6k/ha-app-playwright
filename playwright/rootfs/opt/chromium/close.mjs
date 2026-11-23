// Close Chromium through CDP. Unlike SIGTERM, Browser.close shuts down cleanly
// and writes cookies to disk; SIGTERM loses cookies set in the last ~30 s.
const { webSocketDebuggerUrl } = await (await fetch('http://127.0.0.1:9222/json/version')).json();
const ws = new WebSocket(webSocketDebuggerUrl);
ws.onopen = () => ws.send(JSON.stringify({ id: 1, method: 'Browser.close' }));
ws.onmessage = () => process.exit(0);
ws.onerror = () => process.exit(1);
setTimeout(() => process.exit(1), 5000);
