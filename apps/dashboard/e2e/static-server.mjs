// Header-free static file server for the Playwright projects (ui-spec §7.4, §14.2): behaves like GitHub Pages for
// a Next.js export (`trailingSlash`): `/dir` redirects to `/dir/`, `/dir/` serves `dir/index.html`, an unknown path
// serves the site-root `404.html` with status 404. It sends only Content-Type/Content-Length (no CSP header of ours).
// Usage: node e2e/static-server.mjs <dir> <port>
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";

const [dir, portArg] = process.argv.slice(2);
if (!dir || !portArg) {
    process.stderr.write("usage: static-server.mjs <dir> <port>\n");
    process.exit(2);
}
const root = path.resolve(dir);
const TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
    ".woff2": "font/woff2",
};

async function resolveFile(urlPath) {
    const rel = path.normalize(decodeURIComponent(urlPath)).replace(/^([/\\])+/, "");
    const full = path.join(root, rel);
    if (full !== root && !full.startsWith(root + path.sep)) return { kind: "none" };
    const info = await stat(full).catch(() => null);
    if (info?.isFile()) return { kind: "file", file: full };
    if (info?.isDirectory()) {
        if (!urlPath.endsWith("/")) return { kind: "redirect" };
        const index = path.join(full, "index.html");
        if ((await stat(index).catch(() => null))?.isFile()) return { kind: "file", file: index };
    }
    return { kind: "none" };
}

createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://localhost");
    const found = await resolveFile(url.pathname);
    if (found.kind === "redirect") {
        res.writeHead(301, { Location: `${url.pathname}/${url.search}` }).end();
        return;
    }
    const notFound = found.kind === "none";
    const file = notFound ? path.join(root, "404.html") : found.file;
    const body = await readFile(file).catch(() => null);
    if (body === null) {
        res.writeHead(404, { "Content-Type": "text/plain" }).end("404");
        return;
    }
    const type = TYPES[path.extname(file)] ?? "application/octet-stream";
    res.writeHead(notFound ? 404 : 200, { "Content-Type": type, "Content-Length": body.length });
    res.end(req.method === "HEAD" ? undefined : body);
}).listen(Number(portArg), "127.0.0.1", () =>
    process.stdout.write(`static-server: ${root} on ${portArg}\n`),
);
