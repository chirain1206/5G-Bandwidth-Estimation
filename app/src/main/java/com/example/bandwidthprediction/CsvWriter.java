package com.example.bandwidthprediction;

import android.content.Context;
import java.io.*;

import java.util.Locale;

public class CsvWriter implements Closeable, Flushable {
    private final File file;
    private final Writer out;
    private boolean wroteHeader = false;

    public CsvWriter(Context ctx, String filename) throws IOException {
        File dir = ctx.getExternalFilesDir(null);
        file = new File(dir, filename);
        boolean exists = file.exists();
        out = new BufferedWriter(new OutputStreamWriter(new FileOutputStream(file, true), "UTF-8"));
        wroteHeader = exists; // if file exists we assume header already present
    }

    public File getFile() { return file; }

    public void writeHeader(String... cols) throws IOException {
        if (!wroteHeader) {
            writeRow(cols);
            wroteHeader = true;
        }
    }

    public void writeRow(Object... cols) throws IOException {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < cols.length; i++) {
            if (i > 0) sb.append(',');
            sb.append(escapeCsv(valueOf(cols[i])));
        }
        sb.append('\n');        // ensure a newline per row
        out.write(sb.toString());
    }

    private static String valueOf(Object o) {
        if (o == null) return "";
        if (o instanceof Double || o instanceof Float) {
            // Force dot decimal regardless of device locale
            return String.format(Locale.US, "%.6f", ((Number) o).doubleValue());
        }
        return String.valueOf(o);
    }

    private static String escapeCsv(String s) {
        if (s == null) return "";
        boolean mustQuote = s.contains(",") || s.contains("\"") || s.contains("\n") || s.contains("\r");
        if (mustQuote) {
            s = s.replace("\"", "\"\""); // double internal quotes
            return "\"" + s + "\"";
        }
        return s;
    }

    @Override public synchronized void flush() throws IOException { out.flush(); }
    @Override public synchronized void close() throws IOException { out.close(); }
}