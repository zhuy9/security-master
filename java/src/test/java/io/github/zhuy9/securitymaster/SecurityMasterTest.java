package io.github.zhuy9.securitymaster;

import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;

/** Checks for SecurityMaster against a fake GitHub, a fake clock and a fake environment. No network.
 * A port of tests/test_client.py. Run: mvn -f java/pom.xml verify */
public final class SecurityMasterTest {
    static final String HEADER = "composite_figi,share_class_figi,ticker,figi_ticker,name,security_type,exchange,cik,series_id,class_id,sector,status,first_seen,last_seen\n";
    static final String ROWS = """
            BBG000B9XRY4,BBG001S5N8V8,AAPL,AAPL,APPLE INC,Common Stock,Nasdaq,0000320193,,,Technology,active,2026-10-19,
            BBG000DWG505,BBG001S5PRB1,BRK-B,BRK/B,"BERKSHIRE HATHAWAY, CL B",Common Stock,NYSE,0001067983,,,Financials,active,2026-10-19,
            BBG000OLD001,,XYZ,XYZ,OLD XYZ CORP,Common Stock,NYSE,0000000001,,,Industrials,delisted,2026-10-19,2026-10-20
            BBG000NEW001,,XYZ,XYZ,NEW XYZ ETF,ETP,,,,,,active,2026-10-21,
            """;
    static final String ISSUERS = """
            cik,name,entity_type,sic,sic_description,state_of_incorporation,fiscal_year_end,country
            0000320193,Apple Inc.,operating,3571,Electronic Computers,CA,0926,United States
            0001067983,BERKSHIRE HATHAWAY INC,operating,6331,Fire & Casualty Insurance,DE,1231,United States
            """;
    static final String V1 = "1".repeat(40), V2 = "2".repeat(40), V3 = "3".repeat(40);
    static final Map<String, Map<String, String>> COMMITS = Map.of(
            V1, Map.of("meta.json", "{\"built\": \"2026-10-21\"}", "securities.csv", HEADER + ROWS, "issuers.csv", ISSUERS),
            V2, Map.of("meta.json", "{\"built\": \"2026-10-22\"}", "issuers.csv", ISSUERS, "securities.csv",
                    HEADER + ROWS + "BBG000NVDA01,,NVDA,NVDA,NVIDIA CORP,Common Stock,Nasdaq,0001045810,,,Technology,active,2026-10-22,\n"),
            V3, Map.of("meta.json", "{}", "securities.csv", "ticker,renamed_columns\nAAPL,x\n", "issuers.csv", ISSUERS)); // a schema this client can't read

    static final class FakeGitHub implements SecurityMaster.Http {
        volatile String head = V1;
        volatile boolean offline;
        volatile CountDownLatch entered, gate;
        final List<String> calls = Collections.synchronizedList(new ArrayList<>());
        final List<Integer> headTries = Collections.synchronizedList(new ArrayList<>());

        @Override
        public byte[] get(String url, int tries) throws IOException {
            if (offline) throw new IOException("offline");
            if (url.endsWith("info/refs?service=git-upload-pack")) {
                calls.add("head");
                headTries.add(tries);
                if (gate != null) {
                    entered.countDown();
                    try {
                        gate.await();
                    } catch (InterruptedException e) {
                        throw new IOException(e);
                    }
                }
                return ("001e# service=git-upload-pack\n0000003f" + head + " refs/heads/main\n0000").getBytes(StandardCharsets.UTF_8);
            }
            String[] parts = url.split("/security-master/")[1].split("/data/");
            if (!COMMITS.containsKey(parts[0])) throw new SecurityMaster.HttpStatusException(url, 404);
            calls.add("get " + parts[1] + "@" + parts[0].charAt(0));
            return COMMITS.get(parts[0]).get(parts[1]).getBytes(StandardCharsets.UTF_8);
        }
    }

    static final Map<String, String> env = new HashMap<>();
    static final double[] clock = {1_000_000};

    private SecurityMasterTest() {}

    /** A new "process": empty memory, its own cache directory, a fake GitHub, a fake clock. */
    static FakeGitHub fresh(int ttl, String pin) throws IOException {
        FakeGitHub github = new FakeGitHub();
        SecurityMaster.http = github;
        SecurityMaster.clock = () -> clock[0];
        SecurityMaster.getenv = env::get;
        SecurityMaster.snapshot = null;
        clock[0] = 1_000_000;
        env.clear();
        env.put("SECURITY_MASTER_CACHE", Files.createTempDirectory("sm").toString());
        env.put("SECURITY_MASTER_TTL", Integer.toString(ttl));
        if (pin != null) env.put("SECURITY_MASTER_REF", pin);
        return github;
    }

    static FakeGitHub fresh() throws IOException {
        return fresh(3600, null);
    }

    static void check(boolean ok, Object what) {
        if (!ok) throw new AssertionError(what);
    }

    static <T extends Throwable> T raises(Class<T> type, Runnable body) {
        try {
            body.run();
        } catch (Throwable e) {
            if (type.isInstance(e)) return type.cast(e);
            throw new AssertionError("expected " + type.getSimpleName() + ", got " + e, e);
        }
        throw new AssertionError("expected " + type.getSimpleName());
    }

    static String name(String id) {
        return SecurityMaster.security(id).orElseThrow().name();
    }

    static void testCsvAndTickerOrder() {
        List<List<String>> rows = SecurityMaster.csv("a,\"b,\"\"c\"\"\nd\",e\r\n\r\n\"\",x\r\nlast");
        check(rows.equals(List.of(List.of("a", "b,\"c\"\nd", "e"), List.of(), List.of("", "x"), List.of("last"))), rows);
        // A blank first line is the header, as in DictReader, so the build is unreadable rather than parsed from line 2.
        raises(IllegalArgumentException.class, () -> SecurityMaster.build(new SecurityMaster.Raw("c", "{}", "\n" + HEADER + ROWS, ISSUERS), null, 0));
        // Columns are found by name: reordered and new ones are fine, missing optional ones are "". Blank lines are skipped.
        List<SecurityMaster.Issuer> issuers = SecurityMaster.table("issuers.csv", "new,name,cik\n\nz,Acme,0000000042\n\n",
                SecurityMaster.ISSUER_COLS, v -> new SecurityMaster.Issuer(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]), "cik");
        check(issuers.equals(List.of(new SecurityMaster.Issuer("0000000042", "Acme", "", "", "", "", "", ""))), issuers);
        // Among delisted rows the latest to leave wins a ticker; a tie goes to the later row, as with a stable sort.
        SecurityMaster.Snapshot s = SecurityMaster.build(new SecurityMaster.Raw("c", "{}", HEADER
                + "BBG000000001,,OLD,,A,,,,,,,delisted,,2026-10-02\n" + "BBG000000002,,OLD,,B,,,,,,,delisted,,2026-10-01\n"
                + "BBG000000003,,TIE,,C,,,,,,,delisted,,2026-10-01\n" + "BBG000000004,,TIE,,D,,,,,,,delisted,,2026-10-01\n", ISSUERS), null, 0);
        check(s.byTicker().get("OLD").name().equals("A") && s.byTicker().get("TIE").name().equals("D"), s.byTicker());
    }

    static void testHttpRetriesADroppedConnectionThenGivesUp() throws IOException {
        SecurityMaster.getenv = name -> null; // straight to the local server, whatever this machine's proxy variables say
        AtomicInteger hits = new AtomicInteger();
        List<String> script = Collections.synchronizedList(new ArrayList<>());
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", ex -> {
            hits.incrementAndGet();
            String step = script.isEmpty() ? "drop" : script.remove(0);
            byte[] body = "data".getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().set("Connection", "close");
            if (step.equals("drop")) { // the connection dies mid-body. (One that dies before any byte is resent
                ex.sendResponseHeaders(200, 100); // by HttpClient itself, so a try would reach the server twice.)
                ex.getResponseBody().write(body);
                ex.getResponseBody().flush();
                throw new IOException("drop the connection");
            }
            ex.sendResponseHeaders(Integer.parseInt(step), body.length);
            ex.getResponseBody().write(body);
            ex.close();
        });
        server.start();
        long backoff = SecurityMaster.backoffMillis;
        SecurityMaster.backoffMillis = 1; // no real sleeps
        try {
            String url = "http://127.0.0.1:" + server.getAddress().getPort() + "/x";
            script.addAll(List.of("drop", "drop", "200"));
            check(new String(SecurityMaster.fetch(url, 3), StandardCharsets.UTF_8).equals("data") && hits.get() == 3, hits);
            hits.set(0);
            raises(UncheckedIOException.class, () -> unchecked(() -> SecurityMaster.fetch(url, 1)));
            check(hits.get() == 1, "one try: " + hits);
            hits.set(0);
            raises(UncheckedIOException.class, () -> unchecked(() -> SecurityMaster.fetch(url, 3)));
            check(hits.get() == 3, "three tries: " + hits);
            hits.set(0);
            script.addAll(List.of("503", "200"));
            check(SecurityMaster.fetch(url, 3).length == 4 && hits.get() == 2, "a 5xx is retried: " + hits);
            hits.set(0);
            script.add("404");
            UncheckedIOException e = raises(UncheckedIOException.class, () -> unchecked(() -> SecurityMaster.fetch(url, 3)));
            check(e.getCause() instanceof SecurityMaster.HttpStatusException s && s.code == 404, e);
            check(hits.get() == 1, "a 404 will not get better: no retry, " + hits);
        } finally {
            SecurityMaster.backoffMillis = backoff;
            server.stop(0);
        }
    }

    static void testASlowDownloadFinishesAndAStalledOneTimesOut() throws IOException {
        SecurityMaster.getenv = name -> null;
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", ex -> {
            boolean stall = ex.getRequestURI().getPath().equals("/stall");
            ex.sendResponseHeaders(200, 0); // chunked: each flush reaches the client as it happens
            try (var out = ex.getResponseBody()) {
                for (int i = 0; i < 6; i++) {
                    out.write('x');
                    out.flush();
                    Thread.sleep(stall ? 2000 : 100);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            } catch (IOException e) {
                // the client gave up on /stall
            }
        });
        server.start();
        long idle = SecurityMaster.idleNanos;
        SecurityMaster.idleNanos = TimeUnit.MILLISECONDS.toNanos(400);
        try {
            String base = "http://127.0.0.1:" + server.getAddress().getPort();
            check(SecurityMaster.send(base + "/slow").length == 6, "600 ms in all, but never 400 ms without data: no whole-download cap");
            long start = System.nanoTime();
            UncheckedIOException e = raises(UncheckedIOException.class, () -> unchecked(() -> SecurityMaster.send(base + "/stall")));
            check(e.getCause() instanceof HttpTimeoutException && System.nanoTime() - start < TimeUnit.MILLISECONDS.toNanos(1500),
                    "gives up after 400 ms of silence: " + e);
        } finally {
            SecurityMaster.idleNanos = idle;
            server.stop(0);
        }
    }

    interface Io {
        Object run() throws IOException;
    }

    static void unchecked(Io body) {
        try {
            body.run();
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    static void testABadPinFailsWithAnErrorThatNamesIt() throws IOException {
        fresh(3600, "no-such-tag");
        IllegalStateException e = raises(IllegalStateException.class, () -> SecurityMaster.security("AAPL"));
        check(e.getMessage().contains("SECURITY_MASTER_REF") && e.getMessage().contains("no-such-tag"), e);
    }

    static void testLookups() throws IOException {
        fresh();
        for (String form : List.of("BRK-B", "BRK.B", "brk/b", "BRK B", " BRK-B\u00a0", "BBG000DWG505")) {
            check(SecurityMaster.security(form).orElseThrow().compositeFigi().equals("BBG000DWG505"), form);
        }
        check(name("BRK-B").equals("BERKSHIRE HATHAWAY, CL B"), "quoted comma survives");
        check(name("XYZ").equals("NEW XYZ ETF"), "the active row wins a reused ticker");
        check(SecurityMaster.security("BBG000OLD001").orElseThrow().status().equals("delisted"), "still reachable by FIGI");
        check(SecurityMaster.security("NOPE").isEmpty() && SecurityMaster.issuer(42).isEmpty(), "misses");
        check(SecurityMaster.strip("\u0085\u00a0\u202f\u001c\u3000\t x \u200b ").equals("x \u200b"), "Python's isspace(), not ZWSP");
        check(SecurityMaster.security("AAPL" + " ".repeat(1_000_000) + "X").isEmpty(), "strip is linear: quadratic would take minutes");
        check(SecurityMaster.issuer(320193).orElseThrow().name().equals("Apple Inc.")
                && SecurityMaster.issuer("0000320193").equals(SecurityMaster.issuer(320193)), "CIK with or without zeros");
        check(SecurityMaster.securities().size() == 3 && SecurityMaster.securities(false).size() == 4, "counts");
        check(SecurityMaster.issuers().size() == 2, "issuers");
        check(SecurityMaster.meta().equals(new SecurityMaster.Meta(V1, "{\"built\": \"2026-10-21\"}")), SecurityMaster.meta());
        raises(UnsupportedOperationException.class, () -> SecurityMaster.securities(false).clear()); // callers can't change the data
        for (String[] t : new String[][] {{"inf", "Infinity"}, {"-Infinity", "-Infinity"}, {"3_600", "3600.0"}, {" 60 ", "60.0"}, {"NaN", "NaN"}}) {
            env.put("SECURITY_MASTER_TTL", t[0]);
            check(Double.toString(SecurityMaster.ttl()).equals(t[1]), "TTL as Python's float() reads " + t[0]);
        }
    }

    static void testRefreshesOnlyAfterTheTtlAndOnlyDownloadsANewCommit() throws IOException {
        FakeGitHub github = fresh();
        SecurityMaster.security("AAPL");
        check(github.calls.equals(List.of("head", "get meta.json@1", "get securities.csv@1", "get issuers.csv@1")), github.calls);
        github.calls.clear();
        clock[0] += 3599;
        SecurityMaster.security("AAPL");
        check(github.calls.isEmpty(), "within the TTL: memory only");
        clock[0] += 2;
        SecurityMaster.security("AAPL");
        check(github.calls.equals(List.of("head")), "checked, main had not moved, nothing downloaded: " + github.calls);
        github.calls.clear();
        github.head = V2;
        clock[0] += 3601;
        check(SecurityMaster.security("NVDA").orElseThrow().cik().equals("0001045810"), "the new build is picked up");
        check(github.calls.equals(List.of("head", "get meta.json@2", "get securities.csv@2", "get issuers.csv@2")), github.calls);
        check(SecurityMaster.meta().commit().equals(V2), "meta follows");
        github.calls.clear();
        github.head = V1;
        check(SecurityMaster.refresh().commit().equals(V1) && github.calls.get(0).equals("head"), "refresh() ignores the TTL");
    }

    static void testACheckWithDataInHandTriesOnce() throws IOException {
        FakeGitHub github = fresh();
        SecurityMaster.security("AAPL"); // nothing cached: worth three tries
        clock[0] += 3601;
        SecurityMaster.security("AAPL"); // a copy in hand: one try
        SecurityMaster.refresh(); // asked for by name: three tries
        check(github.headTries.equals(List.of(3, 1, 3)), github.headTries);
    }

    static void testANewProcessReusesARecentlyCheckedDiskCache() throws IOException {
        FakeGitHub github = fresh();
        SecurityMaster.security("AAPL");
        github.calls.clear();
        SecurityMaster.snapshot = null; // a second process sharing the cache directory
        clock[0] += 600;
        check(SecurityMaster.security("AAPL").isPresent() && github.calls.isEmpty(), github.calls);
        SecurityMaster.snapshot = null;
        clock[0] += 3600;
        check(SecurityMaster.security("AAPL").isPresent() && github.calls.equals(List.of("head")), github.calls);
        github.calls.clear();
        SecurityMaster.snapshot = null; // that check touched the file, so the next process skips its own
        clock[0] += 600;
        check(SecurityMaster.security("AAPL").isPresent() && github.calls.isEmpty(), github.calls);
        SecurityMaster.snapshot = null; // but refresh() always checks
        check(SecurityMaster.refresh().commit().equals(V1) && github.calls.equals(List.of("head")), github.calls);
        try (var files = Files.list(Path.of(env.get("SECURITY_MASTER_CACHE")))) {
            List<String> names = files.map(p -> p.getFileName().toString()).toList();
            check(names.equals(List.of("main.java.bin")), "one file, never the Python client's main.json: " + names);
        }
        Path dir = Path.of(env.get("SECURITY_MASTER_CACHE"));
        if (!dir.getFileSystem().supportedFileAttributeViews().contains("posix")) return; // Windows: no modes to compare
        check(Files.getPosixFilePermissions(dir.resolve("main.java.bin")).equals(Files.getPosixFilePermissions(Files.createFile(dir.resolve("probe")))),
                "0666 & ~umask, like Python's file, so other users sharing the directory can read it");
    }

    static void testProxiesFromTheEnvironmentAsUrllibReadsThem() throws IOException {
        fresh();
        HttpServer proxy = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        proxy.createContext("/", ex -> {
            byte[] b = ("via-proxy " + ex.getRequestURI()).getBytes(StandardCharsets.UTF_8);
            ex.sendResponseHeaders(200, b.length);
            ex.getResponseBody().write(b);
            ex.close();
        });
        proxy.start();
        try {
            env.put("http_proxy", "127.0.0.1:" + proxy.getAddress().getPort()); // no scheme, as urllib allows
            check(new String(SecurityMaster.fetch("http://nohost.invalid/x", 1), StandardCharsets.UTF_8).equals("via-proxy http://nohost.invalid/x"), "fetch uses it");
        } finally {
            proxy.stop(0);
        }
        Function<String, String> via = url -> SecurityMaster.PROXIES.select(URI.create(url)).get(0).toString();
        env.put("HTTPS_PROXY", "http://user:pw@proxy.corp");
        check(via.apply("https://github.com/x").equals("HTTP @ proxy.corp/<unresolved>:443"), via.apply("https://github.com/x"));
        env.put("HTTPS_PROXY", "corp_proxy:3128/");
        check(via.apply("https://github.com/x").equals("HTTP @ corp_proxy/<unresolved>:3128"), "a host java.net.URI rejects, split as urllib does");
        env.put("HTTPS_PROXY", "http://user:pw@proxy.corp");
        env.put("no_proxy", " .GitHub.com, other");
        check(via.apply("https://github.com/x").equals("DIRECT") && via.apply("https://api.github.com/x").equals("DIRECT")
                && via.apply("https://raw.githubusercontent.com/x").startsWith("HTTP @ proxy.corp"), "no_proxy is a domain suffix");
        env.put("no_proxy", "*");
        check(via.apply("https://raw.githubusercontent.com/x").equals("DIRECT"), "* bypasses all");
        env.remove("no_proxy");
        env.put("https_proxy", "");
        check(via.apply("https://github.com/x").equals("DIRECT"), "an empty lowercase variable wins over HTTPS_PROXY");
    }

    static void testOfflineServesTheCacheAndRetriesAMinuteLater() throws IOException {
        FakeGitHub github = fresh();
        SecurityMaster.security("AAPL");
        github.offline = true;
        github.calls.clear();
        clock[0] += 3601;
        check(SecurityMaster.security("AAPL").orElseThrow().sector().equals("Technology"), "serves the copy in hand");
        clock[0] += 30;
        SecurityMaster.security("AAPL"); // no retry storm: next attempt is a minute after the failure
        github.offline = false;
        check(github.calls.isEmpty(), github.calls);
        clock[0] += 31;
        SecurityMaster.security("AAPL");
        check(github.calls.equals(List.of("head")), github.calls);

        fresh().offline = true;
        raises(IllegalStateException.class, () -> SecurityMaster.security("AAPL")); // no cache and no network
    }

    static void testRefreshRaisesWhenItsCheckFailsAndTheDataKeepsServing() throws IOException {
        FakeGitHub github = fresh();
        SecurityMaster.security("AAPL");
        github.offline = true;
        raises(UncheckedIOException.class, SecurityMaster::refresh);
        check(SecurityMaster.security("AAPL").orElseThrow().cik().equals("0000320193"), "still serving");
    }

    static void testOfflineKeepsServingMemoryEvenWithoutTheDiskCopy() throws IOException {
        FakeGitHub github = fresh();
        SecurityMaster.security("AAPL");
        try (var files = Files.list(Path.of(env.get("SECURITY_MASTER_CACHE")))) {
            for (Path f : files.toList()) Files.delete(f);
        }
        github.offline = true;
        clock[0] += 3601;
        check(SecurityMaster.security("AAPL").orElseThrow().cik().equals("0000320193"), "memory keeps serving");
    }

    static void testAnUnwritableCacheRunsFromMemoryWithoutRedownloading() throws IOException {
        FakeGitHub github = fresh();
        Path blocker = Files.createTempFile("sm", "a-file");
        env.put("SECURITY_MASTER_CACHE", blocker.resolve("cache").toString()); // mkdir under a file fails
        check(SecurityMaster.security("AAPL").isPresent(), "loads");
        github.calls.clear();
        clock[0] += 3601;
        check(SecurityMaster.security("AAPL").isPresent() && github.calls.equals(List.of("head")), github.calls);

        fresh(3600, V1);
        env.put("SECURITY_MASTER_CACHE", blocker.resolve("cache").toString());
        check(SecurityMaster.security("AAPL").isPresent() && SecurityMaster.security("BRK-B").isPresent(), "pinned, from memory");
    }

    static void testNoHomeDirectoryRunsFromMemory() throws IOException {
        FakeGitHub github = fresh();
        env.remove("SECURITY_MASTER_CACHE");
        String home = System.getProperty("user.home");
        System.setProperty("user.home", "?"); // what the JDK reports for a UID with no passwd entry
        try {
            check(SecurityMaster.cacheFile(null) == null, "nowhere to cache");
            check(SecurityMaster.security("AAPL").orElseThrow().cik().equals("0000320193"), "loads");
            SecurityMaster.snapshot = null; // a new process finds nothing on disk, so it downloads again
            check(SecurityMaster.security("AAPL").isPresent() && Collections.frequency(github.calls, "get securities.csv@1") == 2, github.calls);
        } finally {
            System.setProperty("user.home", home);
        }
    }

    static void testABuildThisClientCannotParseIsNotCachedAndOldDataKeepsServing() throws IOException {
        FakeGitHub github = fresh();
        SecurityMaster.security("AAPL");
        github.head = V3;
        clock[0] += 3601;
        check(SecurityMaster.security("AAPL").orElseThrow().cik().equals("0000320193") && SecurityMaster.meta().commit().equals(V1), "old data");
        Path cache = Path.of(env.get("SECURITY_MASTER_CACHE"), "main.java.bin");
        check(SecurityMaster.read(cache).commit().equals(V1), "the bad build never reached the cache");
        github.calls.clear();
        clock[0] += 30;
        SecurityMaster.security("AAPL");
        check(github.calls.isEmpty(), "retries a minute later, not on every call: " + github.calls);
    }

    static void testAFirstLoadThatFailsSaysWhy() throws IOException {
        fresh().head = V3;
        IllegalStateException e = raises(IllegalStateException.class, () -> SecurityMaster.security("AAPL"));
        check(e.getMessage().contains("has no composite_figi column"), e); // a parse failure, not the network
    }

    static void testOtherThreadsServeTheStaleCopyWhileOneChecks() throws Exception {
        FakeGitHub github = fresh();
        SecurityMaster.security("AAPL");
        github.entered = new CountDownLatch(1);
        github.gate = new CountDownLatch(1);
        clock[0] += 3601;
        Thread checker = new Thread(() -> SecurityMaster.security("AAPL"));
        checker.start();
        github.entered.await(); // the checker is now inside the network call, holding the lock
        check(SecurityMaster.security("AAPL").orElseThrow().ticker().equals("AAPL"), "returns at once instead of queueing");
        github.gate.countDown();
        checker.join();
    }

    static void testAPinnedCommitNeverChecksForUpdates() throws IOException {
        FakeGitHub github = fresh(3600, V1);
        github.head = V2;
        check(SecurityMaster.security("NVDA").isEmpty() && SecurityMaster.meta().commit().equals(V1), "pinned to V1");
        clock[0] += 1e9;
        SecurityMaster.security("AAPL");
        check(!github.calls.contains("head") && Collections.frequency(github.calls, "get securities.csv@1") == 1, github.calls);
    }

    static void testConcurrentCallersShareOneCheck() throws Exception {
        FakeGitHub github = fresh();
        SecurityMaster.security("AAPL");
        github.calls.clear();
        github.head = V2;
        clock[0] += 3601;
        List<Thread> threads = new ArrayList<>();
        for (int i = 0; i < 16; i++) threads.add(new Thread(() -> SecurityMaster.security("AAPL")));
        for (Thread t : threads) t.start();
        for (Thread t : threads) t.join();
        check(Collections.frequency(github.calls, "head") == 1 && Collections.frequency(github.calls, "get securities.csv@2") == 1, github.calls);
    }

    public static void main(String[] args) throws Exception {
        testCsvAndTickerOrder();
        testHttpRetriesADroppedConnectionThenGivesUp();
        testASlowDownloadFinishesAndAStalledOneTimesOut();
        testABadPinFailsWithAnErrorThatNamesIt();
        testLookups();
        testRefreshesOnlyAfterTheTtlAndOnlyDownloadsANewCommit();
        testACheckWithDataInHandTriesOnce();
        testANewProcessReusesARecentlyCheckedDiskCache();
        testOfflineServesTheCacheAndRetriesAMinuteLater();
        testRefreshRaisesWhenItsCheckFailsAndTheDataKeepsServing();
        testOfflineKeepsServingMemoryEvenWithoutTheDiskCopy();
        testAnUnwritableCacheRunsFromMemoryWithoutRedownloading();
        testNoHomeDirectoryRunsFromMemory();
        testABuildThisClientCannotParseIsNotCachedAndOldDataKeepsServing();
        testAFirstLoadThatFailsSaysWhy();
        testOtherThreadsServeTheStaleCopyWhileOneChecks();
        testAPinnedCommitNeverChecksForUpdates();
        testConcurrentCallersShareOneCheck();
        testProxiesFromTheEnvironmentAsUrllibReadsThem();
        System.out.println("19 checks passed");
    }
}
