package com.example.bandwidthprediction;

import android.Manifest;
import android.content.Intent;

import androidx.annotation.NonNull;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.view.View;
import android.widget.Button;
import androidx.appcompat.app.AppCompatActivity;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Timer;
import java.util.TimerTask;
import android.graphics.Color;
import android.widget.Toast;

public class MainActivity extends AppCompatActivity {

    private static final String TAG = "LogToggle";
    private static final int PERMISSION_REQUEST_CODE = 1234;
    private final String[] requiredPermissions = {
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.READ_PHONE_STATE,
            Manifest.permission.ACCESS_NETWORK_STATE
    };

    private boolean isLogging = false;
    private Button logToggleButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        logToggleButton = findViewById(R.id.logToggleButton);
        logToggleButton.setText("Start Logging");
        logToggleButton.setBackgroundColor(Color.GREEN);

//        ActivityCompat.requestPermissions(this,
//                new String[]{Manifest.permission.ACCESS_FINE_LOCATION},
//                PERMISSION_REQUEST_CODE);

        checkAllPermissionsAndStart();

        logToggleButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                if (!isLogging) {
                    Intent serviceIntent = new Intent(MainActivity.this, LoggingService.class);
                    ContextCompat.startForegroundService(MainActivity.this, serviceIntent);
                    logToggleButton.setText("Stop Logging");
                    logToggleButton.setBackgroundColor(Color.RED);
                } else {
                    stopService(new Intent(MainActivity.this, LoggingService.class));
                    logToggleButton.setText("Start Logging");
                    logToggleButton.setBackgroundColor(Color.GREEN);
                }
                isLogging = !isLogging;
            }
        });
    }

    @Override
    protected void onDestroy() {
        stopService(new Intent(this, LoggingService.class));
        super.onDestroy();
    }

//    @Override
//    public void onRequestPermissionsResult(int requestCode,
//                                           @NonNull String[] permissions,
//                                           @NonNull int[] grantResults) {
//        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
//
//        if (requestCode == PERMISSION_REQUEST_CODE) {
//            boolean allGranted = true;
//            for (int result : grantResults) {
//                if (result != PackageManager.PERMISSION_GRANTED) {
//                    allGranted = false;
//                    break;
//                }
//            }
//
//            if (allGranted) {
//                checkAllPermissionsAndStart(); // include MANAGE_EXTERNAL_STORAGE check
//            } else {
//                Toast.makeText(this, "Permissions denied. Closing app.", Toast.LENGTH_LONG).show();
//
//                // Gracefully close app
//                new Handler(Looper.getMainLooper()).postDelayed(() -> {
//                    finishAffinity(); // Close all activities
//                    System.exit(0);   // Terminate process
//                }, 2000); // Short delay to let Toast display
//            }
//        }
//    }

    private void checkAllPermissionsAndStart() {
        List<String> missing = new ArrayList<>();
        for (String perm : requiredPermissions) {
            if (ContextCompat.checkSelfPermission(this, perm) != PackageManager.PERMISSION_GRANTED) {
                missing.add(perm);
            }
        }

//        // MANAGE_EXTERNAL_STORAGE check (API 30+)
//        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
//                !Environment.isExternalStorageManager()) {
//            Intent intent = new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION);
//            startActivity(intent);  // User must enable manually
//            Toast.makeText(this, "Please enable 'All Files Access'", Toast.LENGTH_LONG).show();
//            return;
//        }

        if (!missing.isEmpty()) {
            ActivityCompat.requestPermissions(this,
                    missing.toArray(new String[0]),
                    PERMISSION_REQUEST_CODE);
        }
    }
}