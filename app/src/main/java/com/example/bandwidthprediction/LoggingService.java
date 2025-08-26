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
import java.net.HttpURLConnection;
import java.net.URL;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Executors;

public class LoggingService extends Service {
    private static final String CHANNEL_ID = "BandwidthLogServiceChannel";
    private static final int NOTIFICATION_ID = 1;
    private static final int LOG_INTERVAL = 500; // 500ms
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

        // Write header if file is empty
        if (!logFile.exists()) {
            try (FileWriter writer = new FileWriter(logFile, true)) {
                writer.write("timestamp, latitude, longitude, speed, carrier, network type," +
                        " rssi(dBm), rsrp(dBm), rsrq(dB), snr(dB), cell id," +
                        " downlink avg(Mbps), download variation(Mbps), uplink avg(Mbps), uplink var(Mbps)\n");
            } catch (IOException e) {
                Log.e("Logger", "Failed to write header", e);
            }
        }

        // The logging task to be executed every LOG_INTERVAL
        logTask = new Runnable() {
            @Override
            public void run() {
                String timestamp = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)
                        .format(new Date());
                String[] gpsData = getGpsData();
                String[] netData = getCarrierAndNetworkType();
                String[] signalData = getSignalMetrics();
                String cellId = getCellId();
//                float downloadSpeed = testDownloadSpeed();
                String[] bw = getBandwidthStats();

                String logLine = timestamp + "," +
                        gpsData[0] + "," + gpsData[1] + "," + gpsData[2] + "," +
                        netData[0] + "," + netData[1] + "," +
                        signalData[0] + "," + signalData[1] + "," +
                        signalData[2] + "," + signalData[3] + "," +
                        cellId + "," + bw[0] + "," + bw[1] + "," + bw[2] + "," + bw[3] + "\n";
//                        cellId + "," + downloadSpeed + "\n";

                try (FileWriter writer = new FileWriter(logFile, true)) {
                    writer.append(logLine);
                } catch (IOException e) {
                    Log.e("Logger", "Write failed", e);
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
        handler.post(logTask);
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        // Unregister signal callback
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && signalCallback != null) {
            telephonyManager.unregisterTelephonyCallback((TelephonyCallback) signalCallback);
        }
        handler.removeCallbacks(logTask);
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
//                        case TelephonyManager.NETWORK_TYPE_GPRS:
//                            network = "GPRS";
//                            break;
//                        case TelephonyManager.NETWORK_TYPE_EDGE:
//                            network = "EDGE";
//                            break;
//                        case TelephonyManager.NETWORK_TYPE_UMTS:
//                            network = "UMTS";
//                            break;
//                        case TelephonyManager.NETWORK_TYPE_HSDPA:
//                            network = "HSDPA";
//                            break;
//                        case TelephonyManager.NETWORK_TYPE_HSUPA:
//                            network = "HSUPA";
//                            break;
//                        case TelephonyManager.NETWORK_TYPE_HSPA:
//                            network = "HSPA";
//                            break;
//                        case TelephonyManager.NETWORK_TYPE_HSPAP:
//                            network = "HSPA+";
//                            break;
                        case TelephonyManager.NETWORK_TYPE_LTE:
                            network = "LTE";
                            break;
                        case TelephonyManager.NETWORK_TYPE_NR:
                            network = "5G";
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
    private class MySignalCallback extends TelephonyCallback implements TelephonyCallback.SignalStrengthsListener {
        @Override
        public void onSignalStrengthsChanged(@NonNull SignalStrength signalStrength) {
            latestSignalStrength = signalStrength;
        }
    }

    private String[] getSignalMetrics() {
        String rssi = "N/A", rsrp = "N/A", rsrq = "N/A", snr = "N/A";

        if (latestSignalStrength != null) {
            for (CellSignalStrength signal : latestSignalStrength.getCellSignalStrengths()) {
                rssi = String.valueOf(signal.getDbm());

                if (signal instanceof CellSignalStrengthLte) {
                    CellSignalStrengthLte lte = (CellSignalStrengthLte) signal;
                    rsrp = String.valueOf(lte.getRsrp());
                    rsrq = String.valueOf(lte.getRsrq());
                    snr  = "N/A"; // LTE doesn't expose SNR via public API
                    break;
                } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
                        signal instanceof CellSignalStrengthNr) {
                    CellSignalStrengthNr nr = (CellSignalStrengthNr) signal;
                    rsrp = String.valueOf(nr.getCsiRsrp());
                    rsrq = String.valueOf(nr.getCsiRsrq());
                    snr  = String.valueOf(nr.getCsiSinr()); // 5G SNR equivalent
                    break;
                }
            }
        }

        return new String[]{rssi, rsrp, rsrq, snr};
    }

    private String getCellId() {
        String cellId = "N/A";

        if (ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED) {
            List<CellInfo> cellInfoList = telephonyManager.getAllCellInfo();

            if (cellInfoList != null && !cellInfoList.isEmpty()) {
                for (CellInfo cellInfo : cellInfoList) {
                    if (cellInfo instanceof CellInfoLte) {
                        CellIdentityLte identityLte = (CellIdentityLte) ((CellInfoLte) cellInfo).getCellIdentity();
                        cellId = String.valueOf(identityLte.getCi());
                        break;
                    }
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
                            cellInfo instanceof CellInfoNr) {
                        CellIdentityNr identityNr = (CellIdentityNr) ((CellInfoNr) cellInfo).getCellIdentity();
                        cellId = String.valueOf(identityNr.getNci());
                        break;
                    }
                }
            }
        }

        return cellId;
    }

    private String[] getBandwidthStats() {
        long currentTime = System.currentTimeMillis();
        long currentRx = TrafficStats.getTotalRxBytes();
        long currentTx = TrafficStats.getTotalTxBytes();

        long deltaTime = currentTime - lastBandwidthCheckTime; // in ms
        long deltaRx = currentRx - lastRxBytes;
        long deltaTx = currentTx - lastTxBytes;

        // Convert to Mbps (megabits per second)
        double rxMbps = (deltaTime > 0) ? (deltaRx * 8.0) / deltaTime / 1000.0 : 0;
        double txMbps = (deltaTime > 0) ? (deltaTx * 8.0) / deltaTime / 1000.0 : 0;

        recentRxRates.add((long) (rxMbps * 1_000_000)); // Store in bps for variance
        recentTxRates.add((long) (txMbps * 1_000_000));

        if (recentRxRates.size() > 10) recentRxRates.remove(0);
        if (recentTxRates.size() > 10) recentTxRates.remove(0);

        double rxAvg = rxMbps;
        double txAvg = txMbps;

        double rxVar = recentRxRates.stream()
                .mapToDouble(x -> Math.pow(x / 1_000_000.0 - rxAvg, 2)).average().orElse(0);
        double txVar = recentTxRates.stream()
                .mapToDouble(x -> Math.pow(x / 1_000_000.0 - txAvg, 2)).average().orElse(0);

        // Update previous values
        lastRxBytes = currentRx;
        lastTxBytes = currentTx;
        lastBandwidthCheckTime = currentTime;

        return new String[]{
                String.format("%.3f", rxAvg), String.format("%.3f", rxVar),
                String.format("%.3f", txAvg), String.format("%.3f", txVar)
        };
    }

    private float testDownloadSpeed() {
        try {
            URL url = new URL("https://speed.hetzner.de/100MB.bin"); // example file
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setUseCaches(false);
            connection.connect();

            InputStream input = connection.getInputStream();
            byte[] buffer = new byte[1024];
            int bytesRead;
            long totalBytes = 0;
            long startTime = System.currentTimeMillis();

            while ((bytesRead = input.read(buffer)) != -1 && totalBytes < 1024 * 1024) {
                totalBytes += bytesRead;
            }

            long elapsedTime = System.currentTimeMillis() - startTime;
            input.close();
            connection.disconnect();

            float speedKbps = (totalBytes / 1024f) / (elapsedTime / 1000f) * 8f;
            return speedKbps;

        } catch (Exception e) {
            e.printStackTrace();
            return -1;
        }
    }
}
