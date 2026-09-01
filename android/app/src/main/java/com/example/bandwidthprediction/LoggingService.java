package com.example.bandwidthprediction;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.net.TrafficStats;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.Process;
import android.telephony.CellIdentityLte;
import android.telephony.CellIdentityNr;
import android.telephony.CellInfo;
import android.telephony.CellInfoLte;
import android.telephony.CellInfoNr;
import android.telephony.CellSignalStrengthLte;
import android.telephony.CellSignalStrengthNr;
import android.telephony.TelephonyDisplayInfo;
import android.telephony.TelephonyManager;
import android.telephony.TelephonyCallback;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.RequiresApi;
import androidx.core.app.ActivityCompat;
import androidx.core.app.NotificationCompat;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.Collections;
import java.util.Comparator;

public class LoggingService extends Service {

    private static final String CHANNEL_ID = "BandwidthLoggingChannel";
    private static final int NOTIFICATION_ID = 1;
    private static final int LOG_INTERVAL = 1000; // 1 second (1Hz), Writing Frequency
    private static final int REFRESH_INTERVAL_TICKS = 1; // Refresh modem ticks interval (1 seconds)

    // Server Config
    // 注意：以下是实验期间使用的临时服务器地址，可能已失效。
    // TODO: 采集数据前替换为你自己的服务器地址（搭建方法见仓库 README 的 server/ 目录说明）
    // 下载用 Nginx (Port 80) -> 效率高
    private static final String DL_URL = "http://150.136.250.105/big.bin";
    // 上传用 Python (Port 8081) -> 接收流
    private static final String UL_URL = "http://172.190.185.191:8081/sample_upload";

    private static final int PROBE_STREAMS = 8;
    private static final int PROBE_SECONDS = 15;

    private TelephonyManager telephonyManager;
    private LocationManager locationManager;
    private PowerManager.WakeLock wakeLock; // 防止 CPU 休眠
    private CsvWriter csvWriter;
    private Handler handler = new Handler(Looper.getMainLooper());

    private String currentLogMode = "down";
    private volatile boolean isServiceRunning = false;
    private volatile long currentPhaseStartTime = 0;

    // GPS Cache
    private double lastLat = 0.0;
    private double lastLon = 0.0;
    private float lastSpeed = 0.0f;

    // Bandwidth Stats Cache
    private long lastRxBytes = 0;
    private long lastTxBytes = 0;
    private long lastBandwidthCheckTime = 0;
    private List<Long> recentRxRates = new ArrayList<>();
    private List<Long> recentTxRates = new ArrayList<>();

    // 5G Display Info Cache
    private int currentNetworkOverride = 0;
    private Object displayInfoListener; // Keep reference to prevent GC

    // 缓存上一次有效的信号数据
    private String[] cachedSignals = null;
    private long lastSignalCacheTime = 0;

    // Loop Counter for throttling
    private int loopCount = 0;

    @Override
    public void onCreate() {
        super.onCreate();

        telephonyManager = (TelephonyManager) getSystemService(Context.TELEPHONY_SERVICE);
        locationManager = (LocationManager) getSystemService(Context.LOCATION_SERVICE);

        // 获取 WakeLock (核心修改: 保持 CPU 唤醒，减少断连)
        PowerManager powerManager = (PowerManager) getSystemService(POWER_SERVICE);
        wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "BandwidthLog:KeepAlive");
        wakeLock.acquire();

        // Init CSV
        try {
            csvWriter = new CsvWriter(getApplicationContext(), "bandwidth_traces.csv");
            // Write Header
            csvWriter.writeHeader(
                    "Timestamp", "Latitude", "Longitude", "Speed", "Carrier", "Network Type",
                    "State", // down/up/idle

                    // --- Signal Metrics ---
                    "LTE_RSSI", "LTE_RSRP", "LTE_RSRQ", "LTE_SNR", "LTE_CQI",
                    "NR_SS_RSRP", "NR_SS_RSRQ", "NR_SS_SINR", "NR_CQI",
                    "NR_CSI_RSRP", "NR_CSI_RSRQ", "NR_CSI_SINR",

                    // --- Cell Identifiers ---
                    "LTE_ECI", "LTE_EARFCN", "LTE_PCI",
                    "NR_NCI", "NR_ARFCN", "NR_PCI",

                    // --- Throughput Targets ---
                    "Downlink Avg(Mbps)", "Download Variation(Mbps)",
                    "Uplink Avg(Mbps)", "Uplink Var(Mbps)",

                    // --- Extra ---
                    "Probe Elapsed Time(ms)",

                    // --- [新增] SCell 1 (6 columns) ---
                    "SCell1_Type", "SCell1_PCI", "SCell1_RSSI", "SCell1_RSRP", "SCell1_RSRQ", "SCell1_SNR",
                    // --- [新增] SCell 2 (6 columns) ---
                    "SCell2_Type", "SCell2_PCI", "SCell2_RSSI", "SCell2_RSRP", "SCell2_RSRQ", "SCell2_SNR",
                    // --- [新增] SCell 3 (6 columns) ---
                    "SCell3_Type", "SCell3_PCI", "SCell3_RSSI", "SCell3_RSRP", "SCell3_RSRQ", "SCell3_SNR"
            );
        } catch (IOException e) {
            Log.e("LoggingService", "Failed to init CSV", e);
        }

        registerListeners();
    }

    @SuppressLint("MissingPermission")
    private void registerListeners() {
        // 注册 GPS 监听 (核心修改: 500ms 间隔，诱导 Modem 全速扫描)
        // 1. Location
        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            locationManager.requestLocationUpdates(LocationManager.GPS_PROVIDER, 0, 0, locationListener);
        }

        // 2. Display Info (5G Icon Logic)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            displayInfoListener = new TelephonyCallbackImpl();
            telephonyManager.registerTelephonyCallback(getMainExecutor(), (TelephonyCallback) displayInfoListener);
        }
    }

    @RequiresApi(api = Build.VERSION_CODES.S)
    private class TelephonyCallbackImpl extends TelephonyCallback implements TelephonyCallback.DisplayInfoListener {
        @Override
        public void onDisplayInfoChanged(@NonNull TelephonyDisplayInfo telephonyDisplayInfo) {
            currentNetworkOverride = telephonyDisplayInfo.getOverrideNetworkType();
        }
    }

    private final LocationListener locationListener = new LocationListener() {
        @Override
        public void onLocationChanged(@NonNull Location location) {
            lastLat = location.getLatitude();
            lastLon = location.getLongitude();
            lastSpeed = location.getSpeed();
        }
    };

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        createNotificationChannel();
        Notification notification = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("Bandwidth Trace Logging")
                .setContentText("Collecting 5G Data (Active Polling)...")
                .setSmallIcon(android.R.drawable.ic_menu_upload)
                .setOngoing(true)
                .build();
        startForeground(NOTIFICATION_ID, notification);

        if (intent != null) {
            String mode = intent.getStringExtra("LOG_MODE"); // "up" or "down"
            if (mode != null) currentLogMode = mode;
        }

        isServiceRunning = true;

        // Start Logging Loop
        handler.removeCallbacks(logTask);
        handler.post(logTask);

        // Start Probing Thread
        new Thread(() -> {
            while (isServiceRunning) {
                currentPhaseStartTime = System.currentTimeMillis();
                if ("down".equals(currentLogMode)) {
                    runDownloadPhase(DL_URL, PROBE_STREAMS, PROBE_SECONDS);
                } else {
                    runUploadPhase(UL_URL, PROBE_STREAMS, PROBE_SECONDS);
                }
            }
        }).start();

        return START_STICKY;
    }

    // =========================================================================
    // CORE LOGGING LOOP (Hybrid: 1Hz Logging / 0.2Hz Refresh)
    // =========================================================================
    private Runnable logTask = new Runnable() {
        @SuppressLint("MissingPermission")
        @Override
        public void run() {
            // Check Permissions
            if (ActivityCompat.checkSelfPermission(LoggingService.this, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                return;
            }

            // 1. ALWAYS LOG using current system cache (Fast, Non-blocking)
            // This ensures we write a row every second without fail.
            List<CellInfo> cachedInfo = telephonyManager.getAllCellInfo();
            writeLogToCsv(cachedInfo);

            // 2. CONDITIONALLY REFRESH the modem (Slow, Rate-Limited)
            // Only request an update every REFRESH_INTERVAL_TICKS seconds (REFRESH_INTERVAL_TICKS ticks)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                if (loopCount % REFRESH_INTERVAL_TICKS == 0) {
                    try {
                        telephonyManager.requestCellInfoUpdate(getMainExecutor(), new TelephonyManager.CellInfoCallback() {
                            @Override
                            public void onCellInfo(@NonNull List<CellInfo> cellInfo) {
                                // Success! System cache is now updated.
                                // We do NOT write to CSV here. The next loop of logTask will pick up this new data via getAllCellInfo().
                                 Log.d("LoggingService", "Modem refreshed successfully");
                            }

                            @Override
                            public void onError(int errorCode, Throwable detail) {
                                if (errorCode == TelephonyManager.CellInfoCallback.ERROR_MODEM_ERROR) {
                                    Log.e("LoggingService", "被限流了！Modem 拒绝请求 (ERROR_MODEM_ERROR)");
                                    // 策略：可以在这里暂停 Active Scan 10秒，避风头
                                } else if (errorCode == TelephonyManager.CellInfoCallback.ERROR_TIMEOUT) {
                                    Log.e("LoggingService", "Modem 超时，可能过热或忙碌");
                                }
                            }
                        });
                    } catch (Exception e) {
                        Log.e("LoggingService", "Error requesting cell info update", e);
                    }
                }
            }

            loopCount++;
            handler.postDelayed(this, LOG_INTERVAL); // Schedule next run in 1s
        }
    };

    private void writeLogToCsv(List<CellInfo> cellInfoList) {
        long currentTime = System.currentTimeMillis();
        String timestamp = new SimpleDateFormat("yyyy.MM.dd_HH.mm.ss.SSS", Locale.US).format(new Date());

        String[] gps = {String.valueOf(lastLat), String.valueOf(lastLon), String.valueOf(lastSpeed)};
        String[] net = getCarrierAndNetworkType();
        String[] bw = getBandwidthStats();

        // 注意：这里的 signals 数组现在包含了 30 个元素
        // Index 0-11: PCell (主小区)
        // Index 12-29: SCells (3个辅小区 * 6个指标)
        String[] signals = getSignalMetricsFromCellInfo(cellInfoList);
        String[] ids = getCellInfoStruct(cellInfoList);

        long elapsed = (currentPhaseStartTime > 0) ? (currentTime - currentPhaseStartTime) : 0;

        try {
            // 使用 List 来构建整行数据，比手写几十个参数更安全
            List<String> rowData = new ArrayList<>();

            // 1. 基础信息 (Timestamp, GPS, Net, State)
            rowData.add(timestamp);
            rowData.add(gps[0]); rowData.add(gps[1]); rowData.add(gps[2]);
            rowData.add(net[0]); rowData.add(net[1]); rowData.add(currentLogMode);

            // 2. PCell Signals (取 signals 数组的前 12 个)
            for (int i = 0; i < 12; i++) {
                rowData.add(signals[i]);
            }

            // 3. IDs (LTE_ECI ... NR_PCI)
            for (String id : ids) {
                rowData.add(id);
            }

            // 4. Bandwidth (DL/UL Stats)
            for (String b : bw) {
                rowData.add(b);
            }

            // 5. Time
            rowData.add(String.valueOf(elapsed));

            // 6. [新增] SCell Signals (取 signals 数组的后 18 个)
            // 从 Index 12 开始，直到 29 (共 30 个元素)
            for (int i = 12; i < 30; i++) {
                rowData.add(signals[i]);
            }

            // 转换成数组并写入
            csvWriter.writeRow(rowData.toArray(new String[0]));
            csvWriter.flush();

        } catch (IOException e) {
            e.printStackTrace();
        }
    }

    // --- Helper Methods ---
    private String[] getSignalMetricsFromCellInfo(List<CellInfo> cellInfoList) {
        // --- Part 1: 原有 PCell 逻辑 (保持不变) ---
        String lteRssi="N/A", lteRsrp="N/A", lteRsrq="N/A", lteSnr="N/A", lteCqi="N/A";
        String nrSsRsrp="N/A", nrSsRsrq="N/A", nrSsSnr="N/A", nrCqi="N/A";
        String nrCsiRsrp="N/A", nrCsiRsrq="N/A", nrCsiSnr="N/A";

        // 临时列表：用于存放候选的 SCell
        List<CellInfo> sCellCandidates = new ArrayList<>();

        boolean foundValidData = false;

        if (cellInfoList != null) {
            for (CellInfo cell : cellInfoList) {
                // >>> 逻辑 A: 注册的主小区 (PCell) <<<
                if (cell.isRegistered()) {
                    if (cell instanceof CellInfoLte) {
                        CellInfoLte lte = (CellInfoLte) cell;
                        CellSignalStrengthLte ss = lte.getCellSignalStrength();

                        if (ss.getRsrp() != CellInfo.UNAVAILABLE) {
                            lteRsrp = String.valueOf(ss.getRsrp());
                            foundValidData = true;
                        }
                        if (ss.getRssi() != CellInfo.UNAVAILABLE) lteRssi = String.valueOf(ss.getRssi());
                        if (ss.getRsrq() != CellInfo.UNAVAILABLE) lteRsrq = String.valueOf(ss.getRsrq());
                        if (ss.getRssnr() != CellInfo.UNAVAILABLE) lteSnr = String.valueOf(ss.getRssnr());

                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            if (ss.getCqi() != CellInfo.UNAVAILABLE) lteCqi = String.valueOf(ss.getCqi());
                        }
                    }
                    else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && cell instanceof CellInfoNr) {
                        CellInfoNr nr = (CellInfoNr) cell;
                        CellSignalStrengthNr ss = (CellSignalStrengthNr) nr.getCellSignalStrength();

                        // 修正：确保 RSRP 有效且为负数 (排除 2147483647)
                        if (ss.getSsRsrp() != CellInfo.UNAVAILABLE && ss.getSsRsrp() < 0) {
                            nrSsRsrp = String.valueOf(ss.getSsRsrp());
                            foundValidData = true;
                        }

                        if (ss.getSsRsrq() != CellInfo.UNAVAILABLE) nrSsRsrq = String.valueOf(ss.getSsRsrq());
                        if (ss.getSsSinr() != CellInfo.UNAVAILABLE) nrSsSnr = String.valueOf(ss.getSsSinr());

                        if (ss.getCsiRsrp() != CellInfo.UNAVAILABLE) nrCsiRsrp = String.valueOf(ss.getCsiRsrp());
                        if (ss.getCsiRsrq() != CellInfo.UNAVAILABLE) nrCsiRsrq = String.valueOf(ss.getCsiRsrq());
                        if (ss.getCsiSinr() != CellInfo.UNAVAILABLE) nrCsiSnr = String.valueOf(ss.getCsiSinr());

                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                            List<Integer> cqiList = ss.getCsiCqiReport();
                            if (cqiList != null && !cqiList.isEmpty()) nrCqi = String.valueOf(cqiList.get(0));
                        }
                    }
                }
                // >>> 逻辑 B: 收集 SCell 候选者 (未注册但有信号) <<<
                else {
                    boolean isCandidate = false;
                    int rsrpCheck = CellInfo.UNAVAILABLE;

                    if (cell instanceof CellInfoLte) {
                        rsrpCheck = ((CellInfoLte) cell).getCellSignalStrength().getRsrp();
                    } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && cell instanceof CellInfoNr) {
                        rsrpCheck = ((CellSignalStrengthNr) ((CellInfoNr) cell).getCellSignalStrength()).getSsRsrp();
                    }

                    // 核心修正：
                    // 1. 必须不等于 UNAVAILABLE (Integer.MAX_VALUE)
                    // 2. 必须小于 0 (RSRP 单位是 dBm，肯定是负数)
                    // 3. 必须大于 -140 (过滤掉极其微弱的噪音)
                    if (rsrpCheck != CellInfo.UNAVAILABLE && rsrpCheck < 0 && rsrpCheck > -140) {
                        isCandidate = true;
                    }

                    if (isCandidate) sCellCandidates.add(cell);
                }
            }
        }

        // --- Part 2: 处理 SCell 数据 (排序并取 Top 3) ---
        // 定义 SCell 结果数组：3个小区 * 6个字段 (Type, PCI, RSSI, RSRP, RSRQ, SNR) = 18
        String[] sCellResults = new String[18];
        for(int i=0; i<18; i++) sCellResults[i] = "N/A";

        if (!sCellCandidates.isEmpty()) {
            // 按 RSRP 降序排序
            Collections.sort(sCellCandidates, new Comparator<CellInfo>() {
                @Override
                public int compare(CellInfo c1, CellInfo c2) {
                    int rsrp1 = -999, rsrp2 = -999;
                    if (c1 instanceof CellInfoLte) rsrp1 = ((CellInfoLte)c1).getCellSignalStrength().getRsrp();
                    else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && c1 instanceof CellInfoNr)
                        rsrp1 = ((CellSignalStrengthNr)((CellInfoNr)c1).getCellSignalStrength()).getSsRsrp();

                    if (c2 instanceof CellInfoLte) rsrp2 = ((CellInfoLte)c2).getCellSignalStrength().getRsrp();
                    else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && c2 instanceof CellInfoNr)
                        rsrp2 = ((CellSignalStrengthNr)((CellInfoNr)c2).getCellSignalStrength()).getSsRsrp();

                    // 再次防御性检查：如果是 MAX_VALUE，视为极小值
                    if (rsrp1 == CellInfo.UNAVAILABLE) rsrp1 = -9999;
                    if (rsrp2 == CellInfo.UNAVAILABLE) rsrp2 = -9999;

                    return Integer.compare(rsrp2, rsrp1);
                }
            });

            // 取前 3 个
            int limit = Math.min(3, sCellCandidates.size());
            for (int i = 0; i < limit; i++) {
                CellInfo cell = sCellCandidates.get(i);
                int base = i * 6; // 每组 6 个字段

                if (cell instanceof CellInfoLte) {
                    CellInfoLte lte = (CellInfoLte) cell;
                    CellSignalStrengthLte ss = lte.getCellSignalStrength();

                    sCellResults[base + 0] = "LTE";
                    sCellResults[base + 1] = String.valueOf(lte.getCellIdentity().getPci());
                    sCellResults[base + 2] = (ss.getRssi() != CellInfo.UNAVAILABLE) ? String.valueOf(ss.getRssi()) : "N/A";
                    sCellResults[base + 3] = String.valueOf(ss.getRsrp());
                    sCellResults[base + 4] = String.valueOf(ss.getRsrq());
                    sCellResults[base + 5] = (ss.getRssnr() != CellInfo.UNAVAILABLE) ? String.valueOf(ss.getRssnr()) : "N/A";

                } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && cell instanceof CellInfoNr) {
                    CellInfoNr nr = (CellInfoNr) cell;
                    CellSignalStrengthNr ss = (CellSignalStrengthNr) nr.getCellSignalStrength();
                    CellIdentityNr id = (CellIdentityNr) nr.getCellIdentity();

                    sCellResults[base + 0] = "NR";
                    sCellResults[base + 1] = (id.getPci() != CellInfo.UNAVAILABLE) ? String.valueOf(id.getPci()) : "N/A";
                    sCellResults[base + 2] = "N/A"; // 5G 没有 RSSI
                    sCellResults[base + 3] = String.valueOf(ss.getSsRsrp());
                    sCellResults[base + 4] = (ss.getSsRsrq() != CellInfo.UNAVAILABLE) ? String.valueOf(ss.getSsRsrq()) : "N/A";
                    sCellResults[base + 5] = (ss.getSsSinr() != CellInfo.UNAVAILABLE) ? String.valueOf(ss.getSsSinr()) : "N/A";
                }
            }
        }

        // --- Part 3: 拼接总数组 (12 PCell + 18 SCell = 30 Total) ---
        String[] currentResult = new String[30];

        // 0-11: PCell
        currentResult[0] = lteRssi; currentResult[1] = lteRsrp; currentResult[2] = lteRsrq;
        currentResult[3] = lteSnr; currentResult[4] = lteCqi;
        currentResult[5] = nrSsRsrp; currentResult[6] = nrSsRsrq; currentResult[7] = nrSsSnr;
        currentResult[8] = nrCqi;
        currentResult[9] = nrCsiRsrp; currentResult[10] = nrCsiRsrq; currentResult[11] = nrCsiSnr;

        // 12-29: SCells
        System.arraycopy(sCellResults, 0, currentResult, 12, 18);

        // --- Part 4: 缓存逻辑 ---
        long now = System.currentTimeMillis();

        if (foundValidData) {
            cachedSignals = currentResult;
            lastSignalCacheTime = now;
            return currentResult;
        } else {
            if (cachedSignals != null && (now - lastSignalCacheTime < 3000)) {
                Log.w("LoggingService", "Using cached signals to fill N/A gap");
                return cachedSignals;
            }
        }

        return currentResult;
    }

    private String[] getCellInfoStruct(List<CellInfo> cellInfoList) {
        String lteEci="N/A", lteEarfcn="N/A", ltePci="N/A";
        String nrNci="N/A", nrArfcn="N/A", nrPci="N/A";

        if (cellInfoList != null) {
            for (CellInfo cell : cellInfoList) {
                if (cell instanceof CellInfoLte) {
                    if (!cell.isRegistered()) continue;

                    CellIdentityLte id = ((CellInfoLte) cell).getCellIdentity();
                    if (id.getCi() != CellInfo.UNAVAILABLE) lteEci = String.valueOf(id.getCi());
                    if (id.getEarfcn() != CellInfo.UNAVAILABLE) lteEarfcn = String.valueOf(id.getEarfcn());
                    if (id.getPci() != CellInfo.UNAVAILABLE) ltePci = String.valueOf(id.getPci());
                } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && cell instanceof CellInfoNr) {
                    CellIdentityNr id = (CellIdentityNr) ((CellInfoNr) cell).getCellIdentity();
                    long nci = id.getNci();
                    if (nci != CellInfo.UNAVAILABLE_LONG) nrNci = String.valueOf(nci);
                    if (id.getNrarfcn() != CellInfo.UNAVAILABLE) nrArfcn = String.valueOf(id.getNrarfcn());
                    if (id.getPci() != CellInfo.UNAVAILABLE) nrPci = String.valueOf(id.getPci());
                }
            }
        }
        return new String[]{lteEci, lteEarfcn, ltePci, nrNci, nrArfcn, nrPci};
    }

    private String[] getBandwidthStats() {
        long currentTime = System.currentTimeMillis();
        int uid = Process.myUid();
        long rx = TrafficStats.getUidRxBytes(uid);
        long tx = TrafficStats.getUidTxBytes(uid);

        if (rx == TrafficStats.UNSUPPORTED) rx = TrafficStats.getTotalRxBytes();
        if (tx == TrafficStats.UNSUPPORTED) tx = TrafficStats.getTotalTxBytes();

        double deltaTime = (currentTime - lastBandwidthCheckTime) / 1000.0;
        if (deltaTime < 0.1) deltaTime = 0.1; // Avoid div by zero

        double rxMbps = ((rx - lastRxBytes) * 8.0) / (deltaTime * 1000000.0);
        double txMbps = ((tx - lastTxBytes) * 8.0) / (deltaTime * 1000000.0);

        if (rxMbps < 0) rxMbps = 0;
        if (txMbps < 0) txMbps = 0;

        recentRxRates.add((long)(rxMbps * 1000));
        if (recentRxRates.size() > 5) recentRxRates.remove(0);

        // Variance calc
        double rxAvg = rxMbps; // instantaneous for logging
        double rxVar = 0;
        for (long r : recentRxRates) rxVar += Math.pow((r/1000.0) - rxAvg, 2);
        rxVar /= recentRxRates.size();

        lastRxBytes = rx;
        lastTxBytes = tx;
        lastBandwidthCheckTime = currentTime;

        return new String[]{
                String.format(Locale.US, "%.3f", rxMbps),
                String.format(Locale.US, "%.3f", rxVar),
                String.format(Locale.US, "%.3f", txMbps),
                "0.000" // Simplified UL Var
        };
    }

    @SuppressLint("MissingPermission")
    private String[] getCarrierAndNetworkType() {
        String carrier = telephonyManager.getNetworkOperatorName();
        String net = "Unknown";

        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED) {
            int type = telephonyManager.getDataNetworkType();

            // 1. 判断是否是 SA (独立组网)
            if (type == TelephonyManager.NETWORK_TYPE_NR) {
                // SA 模式下，依然可能显示 5G+ (例如 T-Mobile SA UC)
                if (currentNetworkOverride == TelephonyDisplayInfo.OVERRIDE_NETWORK_TYPE_NR_ADVANCED) {
                    net = "5G+ (SA)";
                } else {
                    net = "5G (SA)";
                }
            }
            // 2. 判断是否是 LTE 锚点 (NSA 或 纯LTE)
            else if (type == TelephonyManager.NETWORK_TYPE_LTE) {
                if (currentNetworkOverride == TelephonyDisplayInfo.OVERRIDE_NETWORK_TYPE_NR_ADVANCED) {
                    net = "5G+ (NSA)"; // AT&T 常见
                }
                else if (currentNetworkOverride == TelephonyDisplayInfo.OVERRIDE_NETWORK_TYPE_NR_NSA) {
                    net = "5G (NSA)";
                }
                else {
                    net = "LTE";
                }
            }
            else {
                net = "Legacy";
            }
        }
        return new String[]{carrier, net};
    }

    private void runDownloadPhase(String urlStr, int streams, int durationSec) {
        CountDownLatch latch = new CountDownLatch(streams);
        long deadline = System.currentTimeMillis() + durationSec * 1000L;

        for (int i = 0; i < streams; i++) {
            new Thread(() -> {
                try {
                    URL url = new URL(urlStr);
                    HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                    conn.setConnectTimeout(3000);
                    conn.setReadTimeout(3000);
                    conn.setUseCaches(false);
                    conn.setRequestProperty("Accept-Encoding", "identity"); // Prevent GZIP

                    InputStream in = conn.getInputStream();
//                    byte[] buf = new byte[32 * 1024];
                    byte[] buf = new byte[512 * 1024];
                    while (System.currentTimeMillis() < deadline) {
                        if (in.read(buf) == -1) break;
                    }
                    in.close();
                    conn.disconnect();
                } catch (Exception e) {
                    // Log.e("BW", "DL Error", e);
                } finally {
                    latch.countDown();
                }
            }).start();
        }
        try { latch.await(); } catch (InterruptedException e) {}
    }

    private void runUploadPhase(String urlStr, int streams, int durationSec) {
        CountDownLatch latch = new CountDownLatch(streams);
        long deadline = System.currentTimeMillis() + durationSec * 1000L;
        byte[] junk = new byte[16 * 1024];

        for (int i = 0; i < streams; i++) {
            new Thread(() -> {
                try {
                    URL url = new URL(urlStr);
                    HttpURLConnection conn = (HttpURLConnection) url.openConnection();
                    conn.setDoOutput(true);
                    conn.setChunkedStreamingMode(16 * 1024);

                    OutputStream out = conn.getOutputStream();
                    while (System.currentTimeMillis() < deadline) {
                        out.write(junk);
                    }
                    out.close();
                    conn.getInputStream().close(); // Trigger request
                    conn.disconnect();
                } catch (Exception e) {
                } finally {
                    latch.countDown();
                }
            }).start();
        }
        try { latch.await(); } catch (InterruptedException e) {}
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(CHANNEL_ID, "Logging Service", NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(channel);
        }
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    @Override
    public void onDestroy() {
        isServiceRunning = false;
        handler.removeCallbacks(logTask);

        if (wakeLock != null && wakeLock.isHeld()) {
            wakeLock.release();
        }

        if (csvWriter != null) {
            try { csvWriter.close(); } catch (IOException e) {}
        }
        super.onDestroy();
    }
}