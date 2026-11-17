package io.github.zhuy9.securitymaster;

import java.io.*;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Proxy;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.FileTime;
import java.util.*;
import java.util.concurrent.locks.ReentrantLock;
import java.util.function.*;
import java.util.regex.*;

/**
 * Lookups into security-master: US exchange-listed stocks, ETFs and closed-end funds keyed by
 * composite FIGI, with issuer details from SEC EDGAR. A port of the Python client; https://github.com/zhuy9/security-master
 *
 * <pre>
 * SecurityMaster.security("BRK.B")          // by ticker, in any form: BRK.B, BRK/B, BRK B, BRK-B
 * SecurityMaster.security("BBG000DWG505")   // by composite FIGI
 * SecurityMaster.issuer(1067983)            // by SEC CIK
 * SecurityMaster.securities()               // every active row; securities(false) for all
 * SecurityMaster.meta()                     // the commit this data comes from, and meta.json as text
 * </pre>
 *
 * The data is the repo's data/ directory, cached in memory and on disk. Once the copy is older than
 * SECURITY_MASTER_TTL seconds (default 3600), the next call asks GitHub which commit main is at, and
 * if it moved, downloads the files at that commit and swaps the new snapshot in whole. Offline, the
 * copy in hand keeps serving, and other threads keep serving it while one checks. Fields are "" when
 * unknown. Environment: SECURITY_MASTER_TTL, SECURITY_MASTER_REF (a commit or tag to pin; pinned data
 * never refreshes), SECURITY_MASTER_CACHE (default $XDG_CACHE_HOME/security-master, else
 * ~/.cache/security-master; memory only if it isn't writable or there is no home directory). Proxies: https_proxy and
 * no_proxy, as in Python, or Java's -Dhttps.proxyHost.
 */
public final class SecurityMaster {
    public record Security(String compositeFigi, String shareClassFigi, String ticker, String figiTicker, String name,
            String securityType, String exchange, String cik, String seriesId, String classId, String sector,
            String status, String firstSeen, String lastSeen) {}

    public record Issuer(String cik, String name, String entityType, String sic, String sicDescription,
            String stateOfIncorporation, String fiscalYearEnd, String country) {}

    /** The commit the data comes from, and data/meta.json as published (parse it with any JSON library). */
    public record Meta(String commit, String json) {}

    static final String REPO = "zhuy9/security-master";
    static final String[] SECURITY_COLS = {"composite_figi", "share_class_figi", "ticker", "figi_ticker", "name",
            "security_type", "exchange", "cik", "series_id", "class_id", "sector", "status", "first_seen", "last_seen"};
    static final String[] ISSUER_COLS = {"cik", "name", "entity_type", "sic", "sic_description",
            "state_of_incorporation", "fiscal_year_end", "country"};
    static final Pattern FIGI = Pattern.compile("BBG[0-9A-Z]{9}");
    static final Pattern HEAD = Pattern.compile("([0-9a-f]{40}) refs/heads/main\\b");
    static final Pattern HOST_PORT = Pattern.compile("(.*):([0-9]+)", Pattern.DOTALL); // urllib's _splitport

    record Raw(String commit, String meta, String securities, String issuers) {}

    record Snapshot(String commit, String meta, List<Security> rows, Map<String, Security> byFigi,
            Map<String, Security> byTicker, Map<String, Issuer> issuers, double checked) { // checked: +inf when pinned
        Snapshot at(double when) {
            return new Snapshot(commit, meta, rows, byFigi, byTicker, issuers, when);
        }
    }

    /** One GET of a URL with up to {@code tries} attempts. Tests swap it for a fake GitHub. */
    @FunctionalInterface
    interface Http {
        byte[] get(String url, int tries) throws IOException;
    }

    static final class HttpStatusException extends IOException {
        final int code;

        HttpStatusException(String url, int code) {
            super("HTTP " + code + " from " + url);
            this.code = code;
        }
    }

    // Test hooks: the network, the clock (epoch seconds), the environment (Java can't set it), the backoff.
    static Http http = SecurityMaster::fetch;
    static DoubleSupplier clock = () -> System.currentTimeMillis() / 1e3;
    static UnaryOperator<String> getenv = System::getenv;
    static long backoffMillis = 1000;
    static int timeoutMillis = 30_000;

    static final ReentrantLock LOCK = new ReentrantLock();
    static volatile Snapshot snapshot;

    /** Proxies as urllib finds them: https_proxy or HTTPS_PROXY (http_ for http) unless no_proxy names the host. Else Java's
     * own: -Dhttps.proxyHost, which also wins over the variables, or -Djava.net.useSystemProxies=true for the OS settings
     * Python reads on macOS and Windows. null means Java's own. ponytail: no user:pass@ proxy logins; add an
     * Authenticator if one is needed. */
    static Proxy proxy(URI uri) {
        String p = proxyEnv(uri.getScheme()), host = uri.getHost().toLowerCase(Locale.ROOT);
        if (p == null || System.getProperty(uri.getScheme() + ".proxyHost") != null) return null;
        String no = proxyEnv("no");
        if (no != null && (no.equals("*") || Arrays.stream(no.split(",")).map(n -> strip(n).replaceFirst("^\\.+", "").toLowerCase(Locale.ROOT))
                .anyMatch(n -> !n.isEmpty() && (host.equals(n) || host.endsWith("." + n))))) return Proxy.NO_PROXY;
        // Split as urllib's _parse_proxy does, not with URI, which has no host for names like corp_proxy.
        String hostPort = p.replaceFirst("^[^/:]+://", "").replaceFirst("/.*", "");
        hostPort = hostPort.substring(hostPort.lastIndexOf('@') + 1);
        Matcher m = HOST_PORT.matcher(hostPort);
        String proxyHost = m.matches() ? m.group(1) : hostPort;
        if (proxyHost.startsWith("[") && proxyHost.endsWith("]")) proxyHost = proxyHost.substring(1, proxyHost.length() - 1); // IPv6
        int port = m.matches() ? Integer.parseInt(m.group(2)) : uri.getScheme().equals("https") ? 443 : 80; // urllib's defaults
        return new Proxy(Proxy.Type.HTTP, InetSocketAddress.createUnresolved(proxyHost, port));
    }

    private SecurityMaster() {}

    /** A security by composite FIGI or by ticker in any separator form; the active row wins a reused ticker. */
    public static Optional<Security> security(String id) {
        Snapshot s = current();
        String key = strip(id).toUpperCase(Locale.ROOT);
        return Optional.ofNullable(FIGI.matcher(key).matches() ? s.byFigi.get(key) : s.byTicker.get(key.replaceAll("[./ ]", "-")));
    }

    /** An issuer by SEC CIK, with or without leading zeros. */
    public static Optional<Issuer> issuer(String cik) {
        Snapshot s = current();
        String key = strip(cik); // ponytail: no zfill sign handling; a signed CIK misses either way
        return Optional.ofNullable(s.issuers.get("0".repeat(Math.max(0, 10 - key.length())) + key));
    }

    public static Optional<Issuer> issuer(long cik) {
        return issuer(Long.toString(cik));
    }

    public static List<Security> securities() {
        return securities(true);
    }

    public static List<Security> securities(boolean activeOnly) {
        List<Security> rows = current().rows;
        return activeOnly ? rows.stream().filter(r -> r.status().equals("active")).toList() : rows;
    }

    public static List<Issuer> issuers() {
        return List.copyOf(current().issuers.values());
    }

    public static Meta meta() {
        Snapshot s = current();
        return new Meta(s.commit, s.meta);
    }

    /** Check GitHub for a new build now, whatever the TTL. Throws if the check fails; the data in hand keeps serving. */
    public static Meta refresh() {
        LOCK.lock();
        try {
            snapshot = refresh(snapshot, true);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        } finally {
            LOCK.unlock();
        }
        return meta();
    }

    static Snapshot current() {
        Snapshot snap = snapshot;
        if (snap != null && clock.getAsDouble() - snap.checked < ttl()) return snap;
        // Only the first load waits. Once there is a copy, a call that finds another thread mid-check
        // serves that copy instead of queueing behind the network.
        if (snap == null) LOCK.lock();
        else if (!LOCK.tryLock()) return snap;
        try {
            if (snapshot != snap) return snapshot; // another thread refreshed while this one waited
            return snapshot = refresh(snap, false);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        } finally {
            LOCK.unlock();
        }
    }

    static Snapshot refresh(Snapshot old, boolean force) throws IOException {
        String pin = env("SECURITY_MASTER_REF");
        Path path = cacheFile(pin);
        Raw raw = read(path);
        if (pin != null) {
            if (raw != null) return build(raw, old, Double.POSITIVE_INFINITY);
            try {
                raw = download(pin);
            } catch (HttpStatusException e) {
                throw new IllegalStateException("security-master: could not load SECURITY_MASTER_REF='" + pin + "' from GitHub: " + e.getMessage(), e);
            }
            Snapshot snap = build(raw, old, Double.POSITIVE_INFINITY);
            save(path, raw);
            return snap;
        }
        double mtime = raw == null ? Double.NEGATIVE_INFINITY : mtime(path);
        if (!force && old == null && clock.getAsDouble() - mtime < ttl()) return build(raw, null, mtime); // another process checked recently
        try {
            // With a copy to serve, one try: the caller is waiting, and a failed check retries in a minute.
            String head = head(force || (old == null && raw == null) ? 3 : 1);
            if (raw != null && raw.commit.equals(head)) {
                touch(path); // still the latest: processes that start within the TTL skip their check
                return build(raw, old, clock.getAsDouble());
            }
            if (old != null && old.commit.equals(head)) return old.at(clock.getAsDouble()); // memory is current; the disk copy isn't
            Raw fresh = download(head);
            Snapshot snap = build(fresh, old, clock.getAsDouble()); // parse first: a build this client can't read never reaches the cache
            save(path, fresh);
            return snap;
        } catch (IOException | IllegalArgumentException e) { // offline, or a build this client can't parse
            if (force) throw e;
            double retry = clock.getAsDouble() - ttl() + 60; // try again in a minute
            if (old != null) return old.at(retry);
            if (raw == null) throw new IllegalStateException("security-master: no cached data yet, and loading it from GitHub failed: " + e, e);
            return build(raw, null, retry);
        }
    }

    static Snapshot build(Raw raw, Snapshot old, double checked) {
        if (old != null && old.commit.equals(raw.commit)) return old.at(checked); // same data: keep the indexes
        String meta = raw.meta.strip(); // ponytail: no JSON parser in the JDK, so only the shape is checked
        if (!meta.startsWith("{") || !meta.endsWith("}")) throw new IllegalArgumentException("meta.json is not a JSON object");
        List<Security> rows = table("securities.csv", raw.securities, SECURITY_COLS, v -> new Security(v[0], v[1], v[2],
                v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12], v[13]), "composite_figi", "ticker", "status", "last_seen");
        Map<String, Security> byFigi = new HashMap<>(), byTicker = new HashMap<>();
        for (Security r : rows) byFigi.put(r.compositeFigi(), r);
        // Active rows win a ticker; among delisted ones, the latest to leave. List.sort is stable, like sorted().
        List<Security> order = new ArrayList<>(rows);
        order.sort(Comparator.comparing((Security r) -> r.status().equals("active")).thenComparing(Security::lastSeen));
        for (Security r : order) byTicker.put(r.ticker(), r);
        Map<String, Issuer> issuers = new LinkedHashMap<>(); // issuers() keeps file order, like a dict
        for (Issuer i : table("issuers.csv", raw.issuers, ISSUER_COLS, v -> new Issuer(v[0], v[1], v[2], v[3], v[4],
                v[5], v[6], v[7]), "cik")) issuers.put(i.cik(), i);
        return new Snapshot(raw.commit, raw.meta, List.copyOf(rows), byFigi, byTicker, issuers, checked);
    }

    /** Rows of a CSV mapped by header name: new columns are ignored, order doesn't matter, absent ones are "". */
    static <T> List<T> table(String file, String text, String[] cols, Function<String[], T> make, String... required) {
        List<List<String>> rows = csv(text);
        List<String> header = rows.isEmpty() ? List.of() : rows.get(0); // a blank first line is an empty header, as in DictReader
        for (String col : required) {
            if (!header.contains(col)) throw new IllegalArgumentException(file + " has no " + col + " column");
        }
        int[] at = new int[cols.length];
        for (int i = 0; i < cols.length; i++) at[i] = header.lastIndexOf(cols[i]); // a repeated column: the last wins, as in DictReader
        List<T> out = new ArrayList<>(rows.size());
        for (List<String> row : rows.subList(Math.min(1, rows.size()), rows.size())) {
            if (row.isEmpty()) continue; // a blank line
            String[] v = new String[cols.length];
            for (int i = 0; i < cols.length; i++) v[i] = at[i] >= 0 && at[i] < row.size() ? row.get(at[i]) : "";
            out.add(make.apply(v));
        }
        return out;
    }

    /** RFC 4180, as lenient as Python's csv: a quote opens a field only at its start, and a blank line is an empty row. */
    static List<List<String>> csv(String s) {
        List<List<String>> rows = new ArrayList<>();
        List<String> row = new ArrayList<>();
        StringBuilder field = new StringBuilder();
        boolean quoted = false, fresh = true; // fresh: nothing of this field read yet
        for (int i = 0, n = s.length(); i < n; i++) {
            char c = s.charAt(i);
            if (quoted) {
                if (c != '"') field.append(c);
                else if (i + 1 < n && s.charAt(i + 1) == '"') field.append(s.charAt(i++));
                else quoted = false;
            } else if (c == '"' && fresh) {
                quoted = true;
                fresh = false;
            } else if (c == ',') {
                row.add(field.toString());
                field.setLength(0);
                fresh = true;
            } else if (c == '\n' || c == '\r') {
                if (c == '\r' && i + 1 < n && s.charAt(i + 1) == '\n') i++;
                if (!row.isEmpty() || !fresh) row.add(field.toString());
                rows.add(row);
                row = new ArrayList<>();
                field.setLength(0);
                fresh = true;
            } else {
                field.append(c);
                fresh = false;
            }
        }
        if (!row.isEmpty() || !fresh) {
            row.add(field.toString());
            rows.add(row);
        }
        return rows;
    }

    /** main's current commit, from git's ref advertisement: the request `git ls-remote` makes, so no API key or rate limit. */
    static String head(int tries) throws IOException {
        Matcher m = HEAD.matcher(text(http.get("https://github.com/" + REPO + ".git/info/refs?service=git-upload-pack", tries)));
        if (!m.find()) throw new IOException("could not read main's commit from GitHub");
        return m.group(1);
    }

    static Raw download(String commit) throws IOException {
        // Files at a commit are immutable, so the three always match, unlike the CDN-cached branch URLs.
        String base = "https://raw.githubusercontent.com/" + REPO + "/" + commit + "/data/";
        return new Raw(commit, text(http.get(base + "meta.json", 3)), text(http.get(base + "securities.csv", 3)),
                text(http.get(base + "issuers.csv", 3)));
    }

    /** GET with retries: one dropped connection must not fail a whole run. A 4xx is final. */
    static byte[] fetch(String url, int tries) throws IOException {
        for (int attempt = 0; ; attempt++) {
            try {
                return send(url);
            } catch (IOException e) {
                if (attempt >= tries - 1 || e instanceof HttpStatusException s && s.code < 500) throw e;
                try {
                    Thread.sleep(backoffMillis << attempt);
                } catch (InterruptedException x) {
                    Thread.currentThread().interrupt();
                    throw new InterruptedIOException("interrupted between tries of " + url);
                }
            }
        }
    }

    /** One GET with urllib's timeout=30: it bounds the connect and each read, never the whole download, so a slow but
     * steady download finishes and a stalled one gives up. Follows redirects, as urllib does. */
    static byte[] send(String url) throws IOException {
        URI uri = URI.create(url);
        Proxy proxy = proxy(uri);
        HttpURLConnection c = (HttpURLConnection) (proxy == null ? uri.toURL().openConnection() : uri.toURL().openConnection(proxy));
        c.setConnectTimeout(timeoutMillis);
        c.setReadTimeout(timeoutMillis);
        if (c.getResponseCode() / 100 != 2) throw new HttpStatusException(url, c.getResponseCode());
        try (InputStream in = c.getInputStream()) {
            byte[] body = in.readAllBytes();
            long expected = c.getContentLengthLong(); // a connection dropped mid-body reads as an early end, not an error
            if (expected >= 0 && body.length != expected) throw new IOException("got " + body.length + " of " + expected + " bytes from " + url);
            return body;
        }
    }

    /** null when there is nowhere to cache, so the client runs from memory. */
    static Path cacheFile(String pin) {
        // Never <ref>.json, so the Python client can share the directory.
        String name = (pin == null ? "main" : pin).replaceAll("[^A-Za-z0-9._-]", "_") + ".java.xml";
        String root = env("SECURITY_MASTER_CACHE"), xdg = env("XDG_CACHE_HOME"), home = env("HOME");
        if (home == null) home = System.getProperty("user.home");
        try {
            if (root != null) return Path.of(root, name);
            if (xdg != null) return Path.of(xdg, "security-master", name);
            if (home == null || home.isEmpty() || home.equals("?")) return null; // no home directory: the JDK says "?"
            return Path.of(home, ".cache", "security-master", name);
        } catch (InvalidPathException e) {
            return null;
        }
    }

    /** One file, replaced atomically: no process ever reads a half-updated set. Best effort.
     * ponytail: last writer wins, so a slow writer can put back an older commit; bounded by one TTL. */
    static void save(Path path, Raw raw) {
        if (path == null) return;
        Path tmp = null;
        try {
            Files.createDirectories(path.getParent());
            // Python's temp name. Not createTempFile: its 0600 locks out other users sharing the directory; this gets 0666 & ~umask.
            tmp = path.resolveSibling("." + path.getFileName() + "." + ProcessHandle.current().pid() + "." + Thread.currentThread().getId() + ".tmp");
            Properties p = new Properties();
            p.putAll(Map.of("commit", raw.commit, "meta.json", raw.meta, "securities.csv", raw.securities, "issuers.csv", raw.issuers));
            try (OutputStream out = Files.newOutputStream(tmp, StandardOpenOption.CREATE_NEW)) {
                p.storeToXML(out, null);
            }
            Files.move(tmp, path, StandardCopyOption.ATOMIC_MOVE);
            touch(path);
        } catch (IOException e) {
            try {
                if (tmp != null) Files.deleteIfExists(tmp);
            } catch (IOException ignored) {
                // best effort
            }
        }
    }

    /** The cache as XML, which, like the Python client's JSON, fails to parse when cut short.
     * ponytail: XML 1.0 can't hold control characters; data/ has none, and a file that won't parse is just downloaded again. */
    static Raw read(Path path) {
        if (path == null) return null;
        Properties p = new Properties();
        try (InputStream in = Files.newInputStream(path)) {
            p.loadFromXML(in);
        } catch (IOException | IllegalArgumentException e) {
            return null;
        }
        String c = p.getProperty("commit"), m = p.getProperty("meta.json"), s = p.getProperty("securities.csv"), i = p.getProperty("issuers.csv");
        return c == null || m == null || s == null || i == null ? null : new Raw(c, m, s, i);
    }

    static double mtime(Path path) {
        try {
            return Files.getLastModifiedTime(path).toMillis() / 1e3;
        } catch (IOException e) {
            return Double.NEGATIVE_INFINITY;
        }
    }

    static void touch(Path path) {
        try {
            Files.setLastModifiedTime(path, FileTime.fromMillis((long) (clock.getAsDouble() * 1e3)));
        } catch (IOException ignored) {
            // best effort
        }
    }

    /** UTF-8, strictly: a malformed file fails like Python's bytes.decode() instead of turning into U+FFFD. */
    static String text(byte[] b) throws IOException {
        return StandardCharsets.UTF_8.newDecoder().decode(ByteBuffer.wrap(b)).toString();
    }

    /** Python's str.strip(), in linear time: an edge-anchored regex is quadratic on an inner run of spaces. */
    static String strip(String s) {
        int i = 0, j = s.length();
        while (i < j && space(s.charAt(i))) i++;
        while (j > i && space(s.charAt(j - 1))) j--;
        return s.substring(i, j);
    }

    /** Exactly Python's str.isspace() set. */
    static boolean space(char c) {
        return Character.isWhitespace(c) || Character.isSpaceChar(c) || c == '\u0085';
    }

    /** An environment variable, with "" meaning unset, as Python's {@code os.environ.get(...) or default}. */
    static String env(String name) {
        String v = getenv.apply(name);
        return v == null || v.isEmpty() ? null : v;
    }

    /** A proxy variable as urllib reads it: the lowercase name wins, even set to "" (no proxy). */
    static String proxyEnv(String scheme) {
        String v = getenv.apply(scheme + "_proxy");
        if (v == null) v = getenv.apply(scheme.toUpperCase(Locale.ROOT) + "_PROXY");
        return v == null || v.isEmpty() ? null : v;
    }

    /** SECURITY_MASTER_TTL as Python's float() reads it, so inf, nan and 3_600 work too. */
    static double ttl() {
        String v = env("SECURITY_MASTER_TTL");
        if (v == null) return 3600;
        String s = strip(v).toLowerCase(Locale.ROOT).replaceAll("(?<=[0-9])_(?=[0-9])", "");
        return switch (s.replaceFirst("^[+-]", "")) {
            case "inf", "infinity" -> s.startsWith("-") ? Double.NEGATIVE_INFINITY : Double.POSITIVE_INFINITY;
            case "nan" -> Double.NaN;
            default -> Double.parseDouble(s);
        };
    }
}
