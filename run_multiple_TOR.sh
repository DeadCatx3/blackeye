#!/bin/bash

# Define the base directory for Tor configurations and data
TOR_BASE_DIR="./tor_instances"

# Define the Tor configurations (ControlPort, SocksPort)
declare -a TOR_CONFIGS=(
    "9011:9010"
    "9021:9020"
    "9031:9030"
    "9041:9040"
    "9051:9050" # ControlPort:SocksPort
    "9061:9060"
    "9071:9070"
    "9081:9080"
    "9091:9090"
)

# Create the base directory if it doesn't exist
mkdir -p "$TOR_BASE_DIR"

echo "Setting up Tor instances..."

for i in "${!TOR_CONFIGS[@]}"; do
    IFS=':' read -r CONTROL_PORT SOCKS_PORT <<< "${TOR_CONFIGS[$i]}"
    INSTANCE_NAME="tor_instance_$(($i + 1))"
    INSTANCE_DIR="$TOR_BASE_DIR/$INSTANCE_NAME"
    TORRC_PATH="$INSTANCE_DIR/torrc"
    DATA_DIR="$INSTANCE_DIR/data"

    # Create instance directory and data directory
    mkdir -p "$INSTANCE_DIR"
    mkdir -p "$DATA_DIR"

    # Generate torrc file
    cat <<EOF > "$TORRC_PATH"
# Tor configuration for $INSTANCE_NAME
DataDirectory $DATA_DIR
Log notice file $INSTANCE_DIR/notices.log
SocksPort $SOCKS_PORT
ControlPort $CONTROL_PORT
# If you need a password for ControlPort, uncomment and set one.
# HashedControlPassword 16:HASHED_PASSWORD_HERE
CookieAuthentication 1
EOF

    echo "Generated torrc for $INSTANCE_NAME in $TORRC_PATH (SocksPort: $SOCKS_PORT, ControlPort: $CONTROL_PORT)"
done

echo ""
echo "Starting Tor instances in the background. Check logs for status."

for i in "${!TOR_CONFIGS[@]}"; do
    IFS=':' read -r CONTROL_PORT SOCKS_PORT <<< "${TOR_CONFIGS[$i]}"
    INSTANCE_NAME="tor_instance_$(($i + 1))"
    INSTANCE_DIR="$TOR_BASE_DIR/$INSTANCE_NAME"
    TORRC_PATH="$INSTANCE_DIR/torrc"
    
    # Start Tor with its specific torrc file
    # Ensure 'tor' command is in your system's PATH, or provide full path like /usr/bin/tor
    tor -f "$TORRC_PATH" &> "$INSTANCE_DIR/stdout.log" &
    echo "Started $INSTANCE_NAME (PID: $!)"
done

echo ""
echo "All Tor instances started. You can monitor them via their log files in $TOR_BASE_DIR/*/notices.log"
echo "To stop them, you can use 'killall tor' or find their PIDs and kill them individually."
