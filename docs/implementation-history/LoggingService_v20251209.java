package com.example.bandwidthprediction;

import android.Manifest;
import android.app.Service;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.TrafficStats;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Process;
import android.telephony.CellIdentityLte;
import android.telephony.CellIdentityNr;
import android.telephony.CellInfo;
import android.telephony.CellInfoLte;
import android.telephony.CellInfoNr;
import android.telephony.CellSignalStrength;
import android.telephony.CellSignalStrengthLte;
import android.telephony.CellSignalStrengthNr;
import android.telephony.SignalStrength;
import android.telephony.TelephonyCallback;
import android.telephony.TelephonyDisplayInfo;
import android.telephony.TelephonyManager;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.RequiresApi;
import androidx.core.app.ActivityCompat;
import androidx.core.app.NotificationCompat;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;

public class LoggingService extends Service {
    private String currentLogMode = "down";
    private int currentNetworkOverride = 0; // used for distinguishing LTE, 5G and 5G+
    private static final String CHANNEL_ID = "BandwidthLogServiceChannel";
    private static final int NOTIFICATION_ID = 1;
    private static final int LOG_INTERVAL = 1000; // millisecond is the default unit
    private static final String DL_URL = "http://172.190.185.191/big.bin";              // nginx
    private static final String UL_URL = "http://172.190.185.191:8081/sample_upload";     // FastAPI
    private static final int PROBE_STREAMS = 4;     // parallel connections per phase
    private static final int PROBE_SECONDS = 15;    // duration (second) per phase
    private volatile boolean isServiceRunning = false;
    private volatile long currentPhaseStartTime = 0;  // 记录当前这一轮 Active Probe 是什么时间戳开始的
    private Handler handler;
    private Runnable logTask;
    private File logFile;
    private LocationManager locationManager;
    private TelephonyManager telephonyManager;
    private ConnectivityManager connectivityManager;
    private Location lastKnownLocation = null;
    private SignalStrength latestSignalStrength = null;
    private TelephonyCallback signalCallback;
    private long lastRxBytes = 0;
    private long lastTxBytes = 0;
    private long lastBandwidthCheckTime = 0;
    private CsvWriter csvWriter;
    // 用来缓存上一次有效的 ID
    private String lastValidLteId = "N/A";
    private String lastValidNrId = "N/A";

    private final List<Long> recentRxRates = new ArrayList<>();
    private final List<Long> recentTxRates = new ArrayList<>();

    private final LocationListener locationListener = new LocationListener() {
        @Override
        public void onLocationChanged(@NonNull Location location) {
            lastKnownLocation = location;
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();

        handler = new Handler(Looper.getMainLooper());
        File dir = getExternalFilesDir(null);
        logFile = new File(dir, "bandwidth_traces.csv");

        // Initialize CSV writer
        try {
            csvWriter = new CsvWriter(getApplicationContext(), "bandwidth_traces.csv");
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
        try {
            csvWriter.writeHeader(
                    "Timestamp", "Latitude", "Longitude", "Speed", "Carrier", "Network Type", "State",

                    // --- 信号部分 (12列) ---
                    "LTE_RSSI", "LTE_RSRP", "LTE_RSRQ", "LTE_SNR",          // 4列 LTE
                    "NR_SS_RSRP", "NR_SS_RSRQ", "NR_SS_SINR",               // 3列 NR (SS)
                    "NR_CSI_RSRP", "NR_CSI_RSRQ", "NR_CSI_SINR",            // 3列 NR (CSI)
                    "LTE_CQI", "NR_CQI",                                    // 2列 LTE/NR
                    "LTE Cell ID", "LTE_EARFCN",
                    "NR Cell ID",  "NR_ARFCN",
                    // ----------------------

                    "LTE Cell ID", "NR Cell ID",
                    "Downlink Avg(Mbps)", "Download Variation(Mbps)", "Uplink Avg(Mbps)", "Uplink Var(Mbps)", "Probe Elapsed Time(ms)"
//                    "Battery Level", "Application Utilization"
            );
        } catch (IOException e) {
            throw new RuntimeException(e);
        }

        // Initialize location manager
        locationManager = (LocationManager) getSystemService(Context.LOCATION_SERVICE);

        // Initialize telephony manager
        telephonyManager = (TelephonyManager) getSystemService(Context.TELEPHONY_SERVICE);

        // Initialize connectivity manager
        connectivityManager = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);

        // Register location callback
        try {
            locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER, LOG_INTERVAL, 0, locationListener);
            lastKnownLocation = locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER);
        } catch (SecurityException e) {
            Log.e("Logger", "Location permission not granted", e);
        }

        // Register signal callback
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            signalCallback = new MySignalCallback();
            telephonyManager.registerTelephonyCallback(
                    Executors.newSingleThreadExecutor(), signalCallback);
        }

        // Initialize bandwidth stats
        lastRxBytes = TrafficStats.getTotalRxBytes();
        lastTxBytes = TrafficStats.getTotalTxBytes();
        lastBandwidthCheckTime = System.currentTimeMillis();

        // The logging task to be executed every LOG_INTERVAL
        logTask = new Runnable() {
            @Override
            public void run() {
                SimpleDateFormat sdf = new SimpleDateFormat("yyyy.MM.dd_HH.mm.ss.SSS", Locale.US);
                String timestamp = sdf.format(new Date());
                String[] gpsData = getGpsData();
                String[] netData = getCarrierAndNetworkType();
                String[] signalData = getSignalMetrics();
//                String[] cellIds = getCellIds();
                String[] cellLayerInfo = getCellLayerInfo();
                String[] bw = getBandwidthStats();

                // 计算当前距离本轮下载开始过了多久
                long elapsedTime;
                if (currentPhaseStartTime > 0) {
                    elapsedTime = System.currentTimeMillis() - currentPhaseStartTime;
                }
                else{
                    elapsedTime = 0;
                }

                try{
                    csvWriter.writeRow(
                            timestamp, gpsData[0], gpsData[1], gpsData[2], netData[0], netData[1], currentLogMode,

                            // --- 填入 10 个信号数据 ---
                            signalData[0], signalData[1], signalData[2], signalData[3], // LTE
                            signalData[4], signalData[5], signalData[6],                // NR SS
                            signalData[7], signalData[8], signalData[9],                // NR CSI
                            signalData[10], signalData[11],                             // LTE/NR CQI
                            // ------------------------

                            cellLayerInfo[0], // LTE Cell ID
                            cellLayerInfo[1], // LTE_EARFCN (新)
                            cellLayerInfo[2], // NR Cell ID
                            cellLayerInfo[3], // NR_ARFCN (新)
                            bw[0], bw[1], bw[2], bw[3],
                            elapsedTime
                    );
                    csvWriter.flush();
                } catch (IOException e) {
                    Log.e("Logger", "Write failed", e);
//                    throw new RuntimeException(e);
                }

                handler.postDelayed(this, LOG_INTERVAL);
            }
        };
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        createNotificationChannel();
        Notification notification = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("Bandwidth Trace Logging Service")
                .setContentText("Running every 500ms")
                .setSmallIcon(R.drawable.ic_launcher_foreground)
                .setOngoing(true)
                .build();
        startForeground(NOTIFICATION_ID, notification);

        // Read current log mode from intent
        if (intent != null) {
            currentLogMode = intent.getStringExtra("LOG_MODE");
            if (currentLogMode == null) currentLogMode = "down";
        }

        isServiceRunning = true;

        handler.removeCallbacks(logTask);
        handler.post(logTask);

        new Thread(() -> {
            while (isServiceRunning) {
                currentPhaseStartTime = System.currentTimeMillis();

                // 根据模式选择跑哪个
                if ("down".equals(currentLogMode)) {
                    Log.d("Bandwidth", "Starting Download Phase...");
                    runDownloadPhase(DL_URL, PROBE_STREAMS, PROBE_SECONDS);
                } else if ("up".equals(currentLogMode)) {
                    Log.d("Bandwidth", "Starting Upload Phase...");
                    runUploadPhase(UL_URL, PROBE_STREAMS, PROBE_SECONDS);
                }

                // 可选：跑完一轮休息 100ms，防止手机过热，也给 CPU 喘息机会
                // 但为了测极限带宽，也可以不休眠
//                try { Thread.sleep(100); } catch (InterruptedException e) {}
            }
        }).start();

        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        isServiceRunning = false;

        // Unregister signal callback
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && signalCallback != null) {
            telephonyManager.unregisterTelephonyCallback((TelephonyCallback) signalCallback);
        }
        handler.removeCallbacks(logTask);
        if (csvWriter != null) {
            try {
                csvWriter.close();
            } catch (IOException e) {
                e.printStackTrace();
            }
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel serviceChannel = new NotificationChannel(
                    CHANNEL_ID,
                    "Realtime Logging",
                    NotificationManager.IMPORTANCE_LOW
            );
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(serviceChannel);
            }
        }
    }

    private String[] getGpsData() {
        if (lastKnownLocation != null) {
            String latitude = String.valueOf(lastKnownLocation.getLatitude());
            String longitude = String.valueOf(lastKnownLocation.getLongitude());
            String speed = String.format(Locale.US, "%.2f", lastKnownLocation.getSpeed()); // m/s
            return new String[]{latitude, longitude, speed};
        } else {
            return new String[]{"N/A", "N/A", "N/A"};
        }
    }

    private String[] getCarrierAndNetworkType() {
        String carrier = "Unknown";
        String network = "Unknown";
        Network activeNetwork = connectivityManager.getActiveNetwork();
        NetworkCapabilities capabilities = connectivityManager.getNetworkCapabilities(activeNetwork);

        try {
            if (ActivityCompat.checkSelfPermission(this, Manifest.permission.READ_PHONE_STATE)
                    == PackageManager.PERMISSION_GRANTED) {
                carrier = telephonyManager.getNetworkOperatorName();
                int type = telephonyManager.getDataNetworkType();
                if (capabilities == null) {
                    network = "Unknown (Capabilities N/A)";
                } else if (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
                    network = "WIFI";
                } else {
                    switch (type) {
                        case TelephonyManager.NETWORK_TYPE_LTE:
                            network = "LTE";
                            if (currentNetworkOverride == TelephonyDisplayInfo.OVERRIDE_NETWORK_TYPE_NR_NSA) {
                                network = "5G"; // 非独立组网
                            } else if (currentNetworkOverride == TelephonyDisplayInfo.OVERRIDE_NETWORK_TYPE_NR_ADVANCED) {
                                network = "5G+"; // 毫米波或超宽带
                            }
                            break;
                        case TelephonyManager.NETWORK_TYPE_NR:
                            network = "5G (SA)";
                            break;
                        case TelephonyManager.NETWORK_TYPE_UNKNOWN:
                            network = "Cellular (Unknown Type)";
                            break;
                        default:
                            network = "Cellular (Type: " + type + ")";
                    }
                }
            }
        } catch (Exception e) {
            Log.e("Logger", "Error reading carrier/network type", e);
        }

        return new String[]{carrier, network};
    }

    @RequiresApi(api = Build.VERSION_CODES.S)
    private class MySignalCallback extends TelephonyCallback implements TelephonyCallback.SignalStrengthsListener, TelephonyCallback.DisplayInfoListener {
        @Override
        public void onSignalStrengthsChanged(@NonNull SignalStrength signalStrength) {
            latestSignalStrength = signalStrength;
        }

        @Override
        public void onDisplayInfoChanged(@NonNull TelephonyDisplayInfo telephonyDisplayInfo) {
            currentNetworkOverride = telephonyDisplayInfo.getOverrideNetworkType();
        }
    }

    private String[] getSignalMetrics() {
        // 初始化 10 个变量，默认均为 "N/A"

        // --- LTE (4项) ---
        String lteRssi = "N/A", lteRsrp = "N/A", lteRsrq = "N/A", lteSnr = "N/A";

        // --- NR Synchronization Signal (覆盖/基础) (3项) ---
        String nrSsRsrp = "N/A", nrSsRsrq = "N/A", nrSsSnr = "N/A";

        // --- NR Channel State Information (性能/波束) (3项) ---
        String nrCsiRsrp = "N/A", nrCsiRsrq = "N/A", nrCsiSnr = "N/A";

        // --- LTE/NR Channel Quality Indicator (2项) ---
        String lteCqi = "N/A";
        String nrCqi = "N/A";

        if (latestSignalStrength != null) {
            for (CellSignalStrength signal : latestSignalStrength.getCellSignalStrengths()) {

                // ============================
                // 1. 捕获 LTE 信号
                // ============================
                if (signal instanceof CellSignalStrengthLte) {
                    CellSignalStrengthLte lte = (CellSignalStrengthLte) signal;

                    if (lte.getRssi() != CellInfo.UNAVAILABLE)  lteRssi = String.valueOf(lte.getRssi());
                    if (lte.getRsrp() != CellInfo.UNAVAILABLE)  lteRsrp = String.valueOf(lte.getRsrp());
                    if (lte.getRsrq() != CellInfo.UNAVAILABLE)  lteRsrq = String.valueOf(lte.getRsrq());
                    if (lte.getRssnr() != CellInfo.UNAVAILABLE) lteSnr  = String.format(Locale.US, "%.1f", lte.getRssnr() / 10.0);
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                        int cqi = lte.getCqi();
                        if (cqi != CellInfo.UNAVAILABLE) {
                            lteCqi = String.valueOf(cqi);
                        }
                    }
                }

                // ============================
                // 2. 捕获 5G NR 信号
                // ============================
                else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
                        signal instanceof CellSignalStrengthNr) {
                    CellSignalStrengthNr nr = (CellSignalStrengthNr) signal;

                    // --- A. SS (Synchronization Signal) ---
                    if (nr.getSsRsrp() != CellInfo.UNAVAILABLE) nrSsRsrp = String.valueOf(nr.getSsRsrp());
                    if (nr.getSsRsrq() != CellInfo.UNAVAILABLE) nrSsRsrq = String.valueOf(nr.getSsRsrq());
                    if (nr.getSsSinr() != CellInfo.UNAVAILABLE) nrSsSnr  = String.format(Locale.US, "%.1f", (double)nr.getSsSinr());

                    // --- B. CSI (Channel State Information) ---
                    // 注意：在 Idle 状态下这些可能是 N/A，只有打流时才会有值，这正是我们想要的特征
                    if (nr.getCsiRsrp() != CellInfo.UNAVAILABLE) nrCsiRsrp = String.valueOf(nr.getCsiRsrp());
                    if (nr.getCsiRsrq() != CellInfo.UNAVAILABLE) nrCsiRsrq = String.valueOf(nr.getCsiRsrq());
                    if (nr.getCsiSinr() != CellInfo.UNAVAILABLE) nrCsiSnr  = String.format(Locale.US, "%.1f", (double)nr.getCsiSinr());

                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                        // CSI-CQI 通常是一个列表 (List<Integer>)，因为可能有多个波束
                        List<Integer> cqiList = nr.getCsiCqiReport();
                        if (cqiList != null && !cqiList.isEmpty()) {
                            // 我们通常取第一个，或者可以把整个列表转成字符串存下来
                            nrCqi = String.valueOf(cqiList.get(0));
                        }
                    }
                }
            }
        }

        // 返回 10 个字符串
        return new String[]{
                lteRssi, lteRsrp, lteRsrq, lteSnr,
                nrSsRsrp, nrSsRsrq, nrSsSnr,
                nrCsiRsrp, nrCsiRsrq, nrCsiSnr,
                lteCqi, nrCqi
        };
    }

//    private String[] getSignalMetrics() {
//        String lteRsrp = "N/A", lteRsrq = "N/A", lteSnr = "N/A";
//        String nrRsrp = "N/A", nrRsrq = "N/A", nrSnr = "N/A";
//        String rssi = "N/A", rsrp = "N/A", rsrq = "N/A", snr = "N/A";
//
//        if (latestSignalStrength != null) {
//            for (CellSignalStrength signal : latestSignalStrength.getCellSignalStrengths()) {
//                rssi = String.valueOf(signal.getDbm());
//
//                if (signal instanceof CellSignalStrengthLte) {
//                    CellSignalStrengthLte lte = (CellSignalStrengthLte) signal;
//                    rsrp = String.valueOf(lte.getRsrp());
//                    rsrq = String.valueOf(lte.getRsrq());
//                    snr  = "N/A"; // LTE doesn't expose SNR via public API
//                    break;
//                } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
//                        signal instanceof CellSignalStrengthNr) {
//                    CellSignalStrengthNr nr = (CellSignalStrengthNr) signal;
//                    rsrp = String.valueOf(nr.getCsiRsrp());
//                    rsrq = String.valueOf(nr.getCsiRsrq());
//                    snr  = String.valueOf(nr.getCsiSinr()); // 5G SNR equivalent
//                    break;
//                }
//            }
//        }
//
//        return new String[]{rssi, rsrp, rsrq, snr};
//    }

    // 返回数组格式: [LTE_ID, LTE_EARFCN, NR_ID, NR_ARFCN]
    private String[] getCellLayerInfo() {
        String lteId = "N/A";
        String lteEarfcn = "N/A";
        String nrId = "N/A";
        String nrArfcn = "N/A";

        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED) {

            List<CellInfo> cellInfoList = telephonyManager.getAllCellInfo();
            if (cellInfoList != null) {
                for (CellInfo cell : cellInfoList) {
//                    if (!cell.isRegistered()) continue; // 只看当前连接的

                    // --- 1. 获取 LTE 信息 ---
                    if (cell instanceof CellInfoLte) {
                        if (!cell.isRegistered()) continue;

                        CellInfoLte lte = (CellInfoLte) cell;
                        CellIdentityLte identity = lte.getCellIdentity();

                        // 获取 Cell ID (ECI)
                        if (identity.getCi() != CellInfo.UNAVAILABLE) {
                            lteId = String.valueOf(identity.getCi());
                        }
                        // 获取 EARFCN (频点)
                        if (identity.getEarfcn() != CellInfo.UNAVAILABLE) {
                            lteEarfcn = String.valueOf(identity.getEarfcn());
                        }
                    }

                    // --- 2. 获取 5G NR 信息 ---
                    else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
                            cell instanceof CellInfoNr) {
                        CellInfoNr nr = (CellInfoNr) cell;
                        CellIdentityNr identity = (CellIdentityNr) nr.getCellIdentity();

                        // 获取 Cell ID (NCI) - NSA 模式下可能读不到
                        long nci = identity.getNci();
                        if (nci != CellInfo.UNAVAILABLE_LONG) {
                            nrId = String.valueOf(nci);
                        }

                        // 获取 NR-ARFCN (频点) - 关键！
                        // 注意：在 NSA 空闲态，这个值也可能是 UNAVAILABLE，只有打流时会有
                        int nrarfcn = identity.getNrarfcn();
                        if (nrarfcn != CellInfo.UNAVAILABLE) {
                            nrArfcn = String.valueOf(nrarfcn);
                        }
                    }
                }
            }
        }
        return new String[]{lteId, lteEarfcn, nrId, nrArfcn};
    }

    private String[] getCellIds() {
        String currentLteId = "N/A";
        String currentNrId = "N/A";

        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED) {

            List<CellInfo> cellInfoList = telephonyManager.getAllCellInfo();
            if (cellInfoList != null) {
                for (CellInfo cellInfo : cellInfoList) {
//                     关键点1：只看已注册的基站 (即当前连接的)
//                    if (!cellInfo.isRegistered()) continue;

                    // 捕获 LTE ID (NSA 锚点 或 纯 LTE)
                    if (cellInfo instanceof CellInfoLte) {
                        if (!cellInfo.isRegistered()) continue; // LTE 依然要求是注册的锚点

                        CellIdentityLte identity = ((CellInfoLte) cellInfo).getCellIdentity();
                        if (identity.getCi() != CellInfo.UNAVAILABLE) {
                            currentLteId = String.valueOf(identity.getCi());
                        }
                    }

                    // 捕获 5G NR ID (NSA 数据点 或 SA 主点)
                    else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
                            cellInfo instanceof CellInfoNr) {
                        CellIdentityNr identity = (CellIdentityNr) ((CellInfoNr) cellInfo).getCellIdentity();
                        // NCI 是 Long 类型 (36-bit)
                        long nci = identity.getNci();
                        if (nci != CellInfo.UNAVAILABLE_LONG) {
                            currentNrId = String.valueOf(nci);
                        }
                    }
                }
            }
        }

        // 逻辑 A: 如果读到了有效的新 LTE ID，更新缓存；否则复用旧值
        if (!currentLteId.equals("N/A")) {
            lastValidLteId = currentLteId;
        } else {
            // 如果当前是 N/A，我们看看能不能用旧的顶一下
            // (可选优化：可以判断 currentNetworkType 是否仍是 LTE/5G，防止你已经切到 WiFi 了还记录基站 ID)
            currentLteId = lastValidLteId;
        }

        // 逻辑 B: 5G ID 同理
        if (!currentNrId.equals("N/A")) {
            lastValidNrId = currentNrId;
        } else {
            // 对于 5G，只有在网络类型依然显示为 "5G" 时才复用，否则可能是真断开了
            // 简单起见，这里先直接复用
            currentNrId = lastValidNrId;
        }

        return new String[]{currentLteId, currentNrId};
    }

    private String[] getBandwidthStats() {
        long currentTime = System.currentTimeMillis();

        // 只获取当前 App (BandwidthWorker) 的流量，排除其他 App 干扰
        int myUid = Process.myUid();
        long currentRx = TrafficStats.getUidRxBytes(myUid);
        long currentTx = TrafficStats.getUidTxBytes(myUid);

        // 如果设备不支持 UID 统计 (极少数情况)，回退到 Total
        if (currentRx == TrafficStats.UNSUPPORTED) currentRx = TrafficStats.getTotalRxBytes();
        if (currentTx == TrafficStats.UNSUPPORTED) currentTx = TrafficStats.getTotalTxBytes();

        long deltaTime = currentTime - lastBandwidthCheckTime; // in ms
        long deltaRx = currentRx - lastRxBytes;
        long deltaTx = currentTx - lastTxBytes;

        // 防止计数器溢出或重置导致的负数
        if (deltaRx < 0) deltaRx = 0;
        if (deltaTx < 0) deltaTx = 0;

        // 计算 Mbps
        // 公式: (Bytes * 8 bits) / (ms / 1000.0 seconds) / 1,000,000.0 (Megabits)
        double rxMbps = (deltaTime > 0) ? (deltaRx * 8.0) / deltaTime / 1000.0 : 0;
        double txMbps = (deltaTime > 0) ? (deltaTx * 8.0) / deltaTime / 1000.0 : 0;

        // --- 方差计算逻辑 (保持不变，这部分写得很好) ---
        recentRxRates.add((long) (rxMbps * 1_000_000));
        recentTxRates.add((long) (txMbps * 1_000_000));

        // 保持 List 大小为 10 (如果1秒一次，就是过去10秒的波动)
        if (recentRxRates.size() > 10) recentRxRates.remove(0);
        if (recentTxRates.size() > 10) recentTxRates.remove(0);

        double rxAvg = rxMbps; // 注意：这里你用的是瞬时速度作为 Avg，如果你想算滑动平均，需要改逻辑
        double txAvg = txMbps;

        // 计算方差 (Standard Variance)
        double rxVar = recentRxRates.stream()
                .mapToDouble(x -> Math.pow(x / 1_000_000.0 - rxAvg, 2)).average().orElse(0);
        double txVar = recentTxRates.stream()
                .mapToDouble(x -> Math.pow(x / 1_000_000.0 - txAvg, 2)).average().orElse(0);

        // 更新状态
        lastRxBytes = currentRx;
        lastTxBytes = currentTx;
        lastBandwidthCheckTime = currentTime;

        // 返回格式化的字符串
        return new String[]{
                String.format(Locale.US, "%.3f", rxAvg),
                String.format(Locale.US, "%.3f", rxVar),
                String.format(Locale.US, "%.3f", txAvg),
                String.format(Locale.US, "%.3f", txVar)
        };
    }

    // --------- DOWNLOAD PHASE ----------
    private void runDownloadPhase(String url, int streams, int seconds) {
        CountDownLatch latch = new CountDownLatch(streams);
        long deadline = System.currentTimeMillis() + seconds * 1000L;

        for (int s = 0; s < streams; s++) {
            new Thread(() -> {
                byte[] buf = new byte[64 * 1024]; // 64KB Buffer
                HttpURLConnection conn = null;
                InputStream in = null;

                try {
                    // 建立连接
                    conn = (HttpURLConnection) new URL(url).openConnection();
                    conn.setConnectTimeout(5000);
                    conn.setReadTimeout(5000);
                    conn.setUseCaches(false);
                    // 告诉 Nginx 我们不需要压缩，直接要把带宽打满
                    conn.setRequestProperty("Accept-Encoding", "identity");
                    conn.connect();

                    in = conn.getInputStream();
                    int r;

                    // --- 核心循环 ---
                    while (System.currentTimeMillis() < deadline) {
                        // 读取数据到 buf，然后直接覆盖（丢弃），不写入 Flash 存储
                        r = in.read(buf);

                        // 如果读到了文件末尾 (-1)，说明文件太小被下完了
                        // 理论上你应该在服务器生成一个足够大的文件 (2GB+)
                        // 如果真的下完了，就跳出，结束当前线程的测试
                        if (r == -1) break;

                        // Android 底层的 TrafficStats 会自动记录这部分流量
                        // 所以不需要我们手动去 count bytes，getBandwidthStats() 会读系统计数器
                    }

                } catch (Exception e) {
                    Log.e("Bandwidth", "Download failed", e);
                } finally {
                    // 必须关闭流和连接，释放资源
                    try { if (in != null) in.close(); } catch (Exception ignored) {}
                    if (conn != null) conn.disconnect();
                    latch.countDown();
                }
            }, "DL-" + s).start();
        }

        try {
            // 等待所有线程结束（要么时间到了，要么出错了）
            latch.await();
        } catch (InterruptedException e) {
            e.printStackTrace();
        }
    }

    // --------- UPLOAD PHASE ----------
    private void runUploadPhase(String url, int streams, int seconds) {
        CountDownLatch latch = new CountDownLatch(streams);
        long deadline = System.currentTimeMillis() + seconds * 1000L;

        // 预先生成一块 64KB 的垃圾数据，避免在循环里重复分配内存
        final byte[] junkData = new byte[64 * 1024];

        for (int s = 0; s < streams; s++) {
            new Thread(() -> {
                HttpURLConnection conn = null;
                OutputStream out = null;
                try {
                    conn = (HttpURLConnection) new URL(url).openConnection();
                    conn.setDoOutput(true);
                    conn.setRequestMethod("POST");
                    conn.setUseCaches(false);
                    // 关键：开启分块传输 (Chunked)，这样我们就可以无限发送数据，不需要预先知道大小
                    conn.setChunkedStreamingMode(64 * 1024);
                    conn.setRequestProperty("Content-Type", "application/octet-stream");
                    conn.setConnectTimeout(5000);
                    conn.setReadTimeout(5000);
                    conn.connect();

                    out = conn.getOutputStream();

                    // --- 核心循环 ---
                    while (System.currentTimeMillis() < deadline) {
                        out.write(junkData);
                        // 这里的 flush 不是必须每次都调，取决于系统缓冲区，但为了平滑发送可以适度 flush
                        // out.flush();
                    }

                    // 结束时，尝试读取一下响应（很多服务器需要读取响应才会确认上传完成）
                    try { conn.getInputStream().close(); } catch (Exception ignored) {}

                } catch (Exception e) {
                    Log.e("Bandwidth", "Upload failed", e);
                } finally {
                    try { if (out != null) out.close(); } catch (Exception ignored) {}
                    if (conn != null) conn.disconnect();
                    latch.countDown();
                }
            }, "UL-" + s).start();
        }

        try {
            latch.await();
        } catch (InterruptedException e) {
            e.printStackTrace();
        }
    }
}
