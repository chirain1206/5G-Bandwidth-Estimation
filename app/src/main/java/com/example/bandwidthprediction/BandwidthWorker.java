package com.example.bandwidthprediction;

import okhttp3.*;
import okio.BufferedSink;
import okio.BufferedSource;
import java.io.IOException;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;

public class BandwidthWorker {
    private final OkHttpClient client = new OkHttpClient.Builder()
            .retryOnConnectionFailure(true)
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS)
            .writeTimeout(0, TimeUnit.SECONDS)
            .build();

    public interface WindowCb {
        void onWindow(String direction, long windowMs, long bytes, double mbps);
    }

    public void runDownload(String bigBinUrl, int streams, int warmupSec, int measureSec,
                            long windowMs, WindowCb cb) throws InterruptedException {
        final long deadlineNs = System.nanoTime() + TimeUnit.SECONDS.toNanos(warmupSec + measureSec);
        final AtomicLong winBytes = new AtomicLong(0);
        final long[] winStart = { System.currentTimeMillis() };

        Runnable tick = () -> {
            long now = System.currentTimeMillis();
            if (now - winStart[0] >= windowMs) {
                long bytes = winBytes.getAndSet(0);
                double sec = Math.max(0.001, (now - winStart[0]) / 1000.0);
                double mbps = (bytes * 8.0) / (sec * 1e6);
                cb.onWindow("down", now - winStart[0], bytes, mbps);
                winStart[0] = now;
            }
        };

        ExecutorService pool = Executors.newFixedThreadPool(Math.max(1, streams));
        CountDownLatch latch = new CountDownLatch(streams);
        for (int i = 0; i < streams; i++) {
            pool.submit(() -> {
                Request req = new Request.Builder()
                        .url(bigBinUrl) // e.g. http://<vm-ip>/big.bin
                        .header("Cache-Control", "no-cache")
                        .build();
                try (Response resp = client.newCall(req).execute()) {
                    if (!resp.isSuccessful()) throw new IOException("HTTP " + resp.code());
                    BufferedSource src = resp.body().source();
                    okio.Buffer buf = new okio.Buffer();
                    while (System.nanoTime() < deadlineNs) {
                        long r = src.read(buf, 64 * 1024);
                        if (r <= 0) break;
                        winBytes.addAndGet(r);
                        tick.run();
                        buf.clear();
                    }
                } catch (IOException ignored) {
                } finally { latch.countDown(); }
            });
        }
        ScheduledExecutorService ticker = Executors.newSingleThreadScheduledExecutor();
        ticker.scheduleAtFixedRate(tick, windowMs, windowMs, TimeUnit.MILLISECONDS);
        latch.await();
        ticker.shutdownNow();
        pool.shutdownNow();
    }

    public void runUpload(String uploadUrl, int streams, int warmupSec, int measureSec,
                          long windowMs, WindowCb cb) throws InterruptedException {
        final long deadlineNs = System.nanoTime() + TimeUnit.SECONDS.toNanos(warmupSec + measureSec);
        final AtomicLong winBytes = new AtomicLong(0);
        final long[] winStart = { System.currentTimeMillis() };

        Runnable tick = () -> {
            long now = System.currentTimeMillis();
            if (now - winStart[0] >= windowMs) {
                long bytes = winBytes.getAndSet(0);
                double sec = Math.max(0.001, (now - winStart[0]) / 1000.0);
                double mbps = (bytes * 8.0) / (sec * 1e6);
                cb.onWindow("up", now - winStart[0], bytes, mbps);
                winStart[0] = now;
            }
        };

        RequestBody streamingBody = new RequestBody() {
            @Override public MediaType contentType() { return MediaType.parse("application/octet-stream"); }
            @Override public void writeTo(BufferedSink sink) throws IOException {
                byte[] chunk = new byte[64 * 1024];
                // warm-up: ignore windows for the first warmupSec (handled by total deadline)
                while (System.nanoTime() < deadlineNs && sink.isOpen()) {
                    sink.write(chunk);
                    sink.flush();
                    winBytes.addAndGet(chunk.length);
                    tick.run();
                }
            }
        };

        ExecutorService pool = Executors.newFixedThreadPool(Math.max(1, streams));
        CountDownLatch latch = new CountDownLatch(streams);
        for (int i = 0; i < streams; i++) {
            pool.submit(() -> {
                Request req = new Request.Builder()
                        .url(uploadUrl) // e.g. http://<vm-ip>:8081/upload-sink
                        .post(streamingBody).build();
                try (Response resp = client.newCall(req).execute()) {
                    // expect 204 No Content
                } catch (IOException ignored) {
                } finally { latch.countDown(); }
            });
        }
        ScheduledExecutorService ticker = Executors.newSingleThreadScheduledExecutor();
        ticker.scheduleAtFixedRate(tick, windowMs, windowMs, TimeUnit.MILLISECONDS);
        latch.await();
        ticker.shutdownNow();
        pool.shutdownNow();
    }
}