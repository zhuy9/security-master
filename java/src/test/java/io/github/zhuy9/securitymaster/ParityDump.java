package io.github.zhuy9.securitymaster;

import io.github.zhuy9.securitymaster.SecurityMaster.Issuer;
import io.github.zhuy9.securitymaster.SecurityMaster.Security;
import java.lang.reflect.RecordComponent;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

/** Answers the lookups java/check.py lists, on the files in data/, so it can diff them against the Python
 * client's answers. No network. Usage: ParityDump DATA_DIR QUERIES OUT */
final class ParityDump {
    private ParityDump() {}

    public static void main(String[] args) throws Exception {
        Path data = Path.of(args[0]);
        SecurityMaster.snapshot = SecurityMaster.build(new SecurityMaster.Raw("local", read(data, "meta.json"),
                read(data, "securities.csv"), read(data, "issuers.csv")), null, Double.POSITIVE_INFINITY); // pinned: never checks
        List<String> out = new ArrayList<>();
        for (String line : Files.readAllLines(Path.of(args[1]), StandardCharsets.UTF_8)) {
            String[] kq = line.split("\t", 2);
            String q = kq[1];
            switch (kq[0]) {
                case "COLS" -> out.add(names(Security.class) + "\t" + names(Issuer.class));
                case "COUNTS" -> out.add(SecurityMaster.securities().size() + " " + SecurityMaster.securities(false).size()
                        + " " + SecurityMaster.issuers().size());
                case "META" -> out.add(SecurityMaster.meta().commit() + "\t" + esc(SecurityMaster.meta().json()));
                case "ROWS" -> SecurityMaster.securities(false).forEach(r -> out.add(row(r)));
                case "ISSUERS" -> SecurityMaster.issuers().forEach(r -> out.add(row(r)));
                case "SEC" -> out.add(SecurityMaster.security(q).map(ParityDump::row).orElse("NONE"));
                case "CIK" -> out.add(SecurityMaster.issuer(q).map(ParityDump::row).orElse("NONE"));
                case "CIKINT" -> out.add(SecurityMaster.issuer(Long.parseLong(q)).map(ParityDump::row).orElse("NONE"));
                default -> throw new IllegalArgumentException("unknown query: " + line);
            }
        }
        Files.writeString(Path.of(args[2]), String.join("\n", out) + "\n", StandardCharsets.UTF_8);
    }

    static String read(Path dir, String name) throws Exception {
        return SecurityMaster.text(Files.readAllBytes(dir.resolve(name)));
    }

    static String names(Class<?> record) {
        return Arrays.stream(record.getRecordComponents()).map(RecordComponent::getName).collect(Collectors.joining(","));
    }

    /** Every component in declaration order, which the COLS line checks against the builder's columns. */
    static String row(Record r) {
        try {
            List<String> v = new ArrayList<>();
            for (RecordComponent c : r.getClass().getRecordComponents()) v.add(esc((String) c.getAccessor().invoke(r)));
            return String.join("\t", v);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
    }

    static String esc(String v) {
        return v.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r");
    }
}
