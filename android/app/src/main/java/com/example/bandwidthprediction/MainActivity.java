package com.example.bandwidthprediction;

import android.Manifest;
import android.content.Intent;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import androidx.appcompat.app.AppCompatActivity;

import java.util.ArrayList;
import java.util.List;
import android.graphics.Color;
import android.widget.RadioGroup;

public class MainActivity extends AppCompatActivity {

    private static final int PERMISSION_REQUEST_CODE = 1234;
    private final String[] requiredPermissions = {
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.READ_PHONE_STATE,
            Manifest.permission.ACCESS_NETWORK_STATE
    };

    private boolean isLogging = false;
    private Button logToggleButton;
    private RadioGroup logMode;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        logToggleButton = findViewById(R.id.logToggleButton);
        logToggleButton.setText("Start Logging");
        logToggleButton.setBackgroundColor(Color.GREEN);
        logMode = findViewById(R.id.logMode);

        checkAllPermissionsAndStart();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            if (!Environment.isExternalStorageManager()) {
                Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
                intent.setData(Uri.parse("package:" + getPackageName()));
                startActivity(intent);
            }
        }

        logToggleButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                if (!isLogging) {
                    String selectedMode = "down";
                    int selectedId = logMode.getCheckedRadioButtonId();
                    if (selectedId == R.id.rbUplink) {
                        selectedMode = "up";
                    }

                    // Start service
                    Intent serviceIntent = new Intent(MainActivity.this, LoggingService.class);
                    serviceIntent.putExtra("LOG_MODE", selectedMode);
                    ContextCompat.startForegroundService(MainActivity.this, serviceIntent);

                    // UI change
                    logToggleButton.setText("Stop Logging");
                    logToggleButton.setBackgroundColor(Color.RED);
                    // Disable change of radio buttons
                    for (int i = 0; i < logMode.getChildCount(); i++) {
                        logMode.getChildAt(i).setEnabled(false);
                    }
                } else {
                    // Stop service
                    stopService(new Intent(MainActivity.this, LoggingService.class));

                    // UI change
                    logToggleButton.setText("Start Logging");
                    logToggleButton.setBackgroundColor(Color.GREEN);
                    // Enable change of radio buttons
                    for (int i = 0; i < logMode.getChildCount(); i++) {
                        logMode.getChildAt(i).setEnabled(true);
                    }
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

    private void checkAllPermissionsAndStart() {
        List<String> missing = new ArrayList<>();
        for (String perm : requiredPermissions) {
            if (ContextCompat.checkSelfPermission(this, perm) != PackageManager.PERMISSION_GRANTED) {
                missing.add(perm);
            }
        }

        if (!missing.isEmpty()) {
            ActivityCompat.requestPermissions(this,
                    missing.toArray(new String[0]),
                    PERMISSION_REQUEST_CODE);
        }
    }
}