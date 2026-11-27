# YouTube channel connection and scheduled clips

Clipify AI uses Google's official [installed-app OAuth flow with PKCE](https://developers.google.com/identity/protocols/oauth2/native-app) and YouTube Data API v3. It does not need a Google client secret, password, `credentials.json`, or a manually copied access token. Tokens obtained by this flow are stored in the operating system credential vault (Windows Credential Manager, macOS Keychain, or Linux Secret Service/KWallet), not written to project or settings JSON files.

## Privacy and data flow

The YouTube publishing backend runs locally on the computer running Clipify AI and listens only on its loopback address. Project code and generated clips remain on that computer until an upload is explicitly confirmed. Connecting contacts Google for OAuth and YouTube API requests, including a request to identify the authorized channel; Google receives the OAuth authorization and channel identity. After the user confirms an upload or schedule, the selected video bytes and its title, description, and tags are sent to Google/YouTube; scheduled uploads also include their publication times. Videos are hosted by YouTube. There is no zero-transfer guarantee for those operations: this transfer is how YouTube publishing works.

OAuth access and refresh tokens are stored only in the supported OS credential vault, never in the Git repository or application logs. The OAuth client ID is configured locally in `.env`, which is ignored by Git. **Disconnect** deletes Clipify AI's local vault entry; to also revoke Google's grant, visit [Google Account permissions](https://myaccount.google.com/permissions) and remove Clipify AI/its OAuth app. Disconnecting or revoking does not delete or transfer videos already uploaded/scheduled on YouTube. No connection or upload occurs simply by opening the preview.

## Google Cloud setup

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project.
2. Open **APIs & Services → Library**, enable **YouTube Data API v3**.
3. Configure the OAuth consent screen. Set the app audience appropriately; while the app is in Testing, add the Google account that owns the channel as a test user.
4. Open **APIs & Services → Credentials → Create credentials → OAuth client ID** and choose **Desktop app**. Copy its client ID only. Do not copy or share a client secret.
5. Add the client ID to the local `.env` used by Clipify AI:

   ```dotenv
   YOUTUBE_CLIENT_ID=your-desktop-oauth-client-id.apps.googleusercontent.com
   ```

   For an installed app, edit the writable user-data `.env` (normally `%LOCALAPPDATA%\ClippedAI\.env` on Windows), or the `.env` beside a self-contained installation. Alternatively, set the environment variable before launching. Do not put credentials in chat or commit them to the repository.

6. Restart Clipify AI. OAuth uses Google's installed-app loopback redirect on a temporary random port at `http://127.0.0.1:<port>`; the listener exists only during authorization and shuts down afterward. This is separate from Clipify AI's normal web UI port. Select **Desktop app** for the OAuth client; no web-client redirect URI or client secret is needed.

## Connect, trial, and schedule

1. Open **Share & Publish Short → YouTube Shorts → Connect YouTube** and authorize the Google account in Google's page.
2. Clipify AI displays the exact channel name and channel ID returned by Google. Upload and schedule controls stay disabled until you explicitly confirm that exact channel. If it is not the intended channel, disconnect and authorize the correct Google account instead.
3. For the trial, review the first three verified 9:16 outputs shown in **3-clip public Shorts trial**. The user-selected visibility is **Public**: clicking its confirmation publishes exactly those three immediately. The exact confirmed channel and all three filenames are shown again before upload; no other clip or scheduled queue is changed.
4. Review the detected dimensions and format label for each unique 30–50 second generated MP4. Nothing is selected automatically; choose only clips you have approved. Identical files are de-duplicated by SHA-256, and the scanner includes MP4s in generated job output folders and their subfolders.
5. Choose **YouTube Shorts** only for verified 9:16 vertical outputs. Landscape sources cannot be scheduled as Shorts. Clipify AI never silently crops or resizes a video; choose **Standard YouTube videos** if you want to schedule a landscape clip as a regular video, or prepare a separate vertical output first. Originals are never overwritten.
6. Review the proposed schedule. Defaults are 7 clips per day, evenly spaced from 9:00 AM through 9:00 PM Asia/Kolkata, beginning tomorrow. Clip titles, descriptions, and individual ISO 8601 publication times can be edited before applying.
7. **Confirm & upload schedule** is the explicit action that starts scheduled uploads. Each scheduled video is uploaded as private with its YouTube `publishAt` time, so Google publishes it on schedule. The confirmation identifies whether these are 9:16 Shorts or standard videos. Keep Clipify AI open until the upload queue finishes; after YouTube has accepted the scheduled videos, closing Clipify AI does not cancel those YouTube publication times.

No OAuth connection, trial upload, or real schedule is created by setup or by opening the publishing panel or schedule preview. You can disconnect from the same panel, then connect and confirm a different Google/YouTube channel later; OAuth prompts you to select an account. Disconnecting removes the saved OAuth credentials from the OS vault but does not cancel or transfer videos already scheduled in YouTube. Those remain scheduled on the original channel.

## Notes

- The app requires a supported OS credential-vault backend. If the vault is unavailable, Clipify AI refuses to save tokens rather than falling back to plaintext.
- YouTube API quota and channel eligibility limits apply. Google may require the OAuth consent screen to be verified for broader public use.
- YouTube's API quota and channel eligibility limits still apply. The [current quota documentation](https://developers.google.com/youtube/v3/determine_quota_cost) gives `videos.insert` a separate default bucket of 100 calls per day, so a 60-clip batch is within that default upload-call limit. Check Google's current quota page because API policies can change.
- If an upload fails partway through a batch, the panel reports per-clip failures. Already accepted videos remain scheduled in YouTube Studio; check the channel there before retrying failed entries.
