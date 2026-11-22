# SecureLAN Arena

SecureLAN Arena is a Java desktop app for two people on the same local network. One player hosts a session from the app and the other joins using the host's IP address. Once connected, both players can exchange encrypted messages, play two-player games, and talk using a push-to-talk button. The session runs directly between the two app instances.

## Features

| Feature | How it works |
| --- | --- |
| Text chat | Send messages from the **Chat** tab with **Send** or Enter. |
| Tic Tac Toe | The host plays **X** and goes first. The client plays **O**. Moves update both boards. |
| Rock Paper Scissors | Both players choose a move. The app shows the result once both choices arrive. Use **Reset** to start a new round. |
| Walkie-talkie | In the **Chat** tab, press and hold **Hold To Talk** while speaking. Release it to stop transmitting. |

## Run the app

The IntelliJ project is configured for **JDK 23**. The app uses Java Swing, Java Sound, and standard Java networking and cryptography libraries. It has no third-party dependencies.

### IntelliJ IDEA

1. Open the repository folder in IntelliJ IDEA.
2. Select **JDK 23** under **File → Project Structure → Project SDK**.
3. Open [Main.java](src/com/securelanarena/Main.java) and run `Main.main()`.

### Terminal

From the repository root, compile the app and launch it:

```sh
javac -encoding UTF-8 -d out src/com/securelanarena/*.java
java -cp out com.securelanarena.Main
```

To open a second instance on the same computer, run the `java` command again in another terminal.

## Host and join a session

1. Open the app on both devices and go to the **Connection** tab. Enter a display name in each window.
2. On the host, keep the default **Chat port** (`5000`) or choose an available port. Enter a shared password and click **Host Chat**.
3. On the client, enter the host's local IP in **Friend IP address**, use the same chat port and password, and click **Connect**.
4. Once connected, open **Chat** and send a message to verify the session. Use **Disconnect** in the **Connection** tab when finished.

**Testing on one computer?** Use `127.0.0.1` as the host address in the client window. For two devices, connect both to the same local network. On Windows, run `ipconfig` on the host and look for the **IPv4 Address** of the active network adapter. On macOS, `ipconfig getifaddr en0` shows the address if Wi-Fi uses `en0`.

### Network ports

| Traffic | Protocol | Listening port |
| --- | --- | --- |
| Chat messages and game events | TCP | Host's chat port, `5000` by default |
| Voice received by the host | UDP | `6000` on the host |
| Voice received by the client | UDP | `6001` on the client |

If the client cannot connect, check the host IP, chat port, and firewall settings. If the connection opens but messages fail, check that the passwords match exactly. If chat works but voice fails, check microphone access, audio output, and the UDP ports above.

## Encryption

Text messages, game events, and voice packets use AES-128 in Galois/Counter Mode (GCM). Each encrypted payload uses a fresh random initialization vector. The app derives the key by hashing the shared password with SHA-256 and taking the first 16 bytes.

The current design is suited to demonstrations on a trusted local network. Passwords are hashed once without a salt, so captured traffic can be used to test guesses against a weak password. Replace the prefilled example password with a strong shared password for LAN use.

## Source layout

All application code is under [src/com/securelanarena](src/com/securelanarena).

| File | Responsibility |
| --- | --- |
| `Main.java` | Starts the Swing application. |
| `ChatWindow.java` | Builds the interface and handles chat, connection controls, and game state. |
| `ChatServer.java` | Accepts one client and exchanges encrypted messages over TCP. |
| `ChatClient.java` | Connects to the host and exchanges encrypted messages over TCP. |
| `VoiceChat.java` | Captures and plays audio and sends encrypted voice packets over UDP. |
| `CryptoUtil.java` | Derives the encryption key and encrypts or decrypts text and audio. |

## Project team

| Team member | Contributions |
| --- | --- |
| Grid | Application entry point, Swing interface, chat and connection screens, game screens, and documentation. |
| Atida | Client and server networking, message transport, AES-GCM encryption, and encrypted push-to-talk audio. |
