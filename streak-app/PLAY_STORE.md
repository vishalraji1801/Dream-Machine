# Publishing Streak on Google Play

The plan: wrap the hosted web version as a Trusted Web Activity (a real Android app that opens your website full screen). This keeps Google and Microsoft sign-in working, because they run in Chrome rather than an embedded browser. You need **no Android Studio**.

## Costs

- Google Play developer account: **$25 one time**.
- Everything else (Firebase, PWABuilder) is free.

## Before you start

1. Finish **SETUP.md** so the web version is live at `https://YOUR-PROJECT.web.app`.
2. Open **privacy.html** and replace `[YOUR CONTACT EMAIL]` and `[YOUR NAME]`, then redeploy (`npx firebase-tools deploy`). Your policy URL is `https://YOUR-PROJECT.web.app/privacy.html`.
3. Check it installs from Chrome on your phone and sign-in works.

## Build the Android package

1. Go to <https://www.pwabuilder.com>, enter your site URL, and click **Start**.
2. Click **Package for stores > Android**.
3. Choose a **Package ID** such as `com.yourname.streak`. It can never change after you publish. Leave signing on **New** (it creates a signing key for you).
4. Download the zip. It contains the **.aab** file (this is what you upload), a **signing key file with its passwords**, and **assetlinks.json**.
5. **Back up the signing key and passwords somewhere safe.** If you lose them you cannot update the app.

## Link the app to your website (needed to hide the browser bar)

1. Create a folder `.well-known` in the project and put the zip's **assetlinks.json** inside it (see **assetlinks.template.json** for the shape).
2. Run `npx firebase-tools deploy`.
3. Check `https://YOUR-PROJECT.web.app/.well-known/assetlinks.json` opens in a browser.
4. After you upload to Google Play, open Play Console > **Setup > App signing** and copy the **SHA-256 certificate fingerprint** that Google signs with. Add it to the `sha256_cert_fingerprints` list in assetlinks.json too and deploy again. Without this the installed app shows a browser address bar.

## Play Console

1. Create the account at <https://play.google.com/console> and verify your identity.
2. **Create app**: name Streak, app (not game), free.
3. **Store listing**: short description (up to 80 characters), full description, app icon (**icons/icon-512.png**), a **feature graphic 1024x500**, and at least **2 phone screenshots**. I can generate the graphic and screenshots from the app if you ask.
4. **Privacy policy**: your `privacy.html` URL.
5. **App content** forms:
   - **Data safety**: collects *email address* (account) and *user-generated content* (habit data); data is encrypted in transit; users can request deletion. No data is sold or shared for ads.
   - **Account deletion**: in-app path = Account > Delete account. Web link = `https://YOUR-PROJECT.web.app/privacy.html#delete`.
   - **Content rating** questionnaire (no violence, no ads, no user-to-user content).
   - **Target audience**: 13 and over. Ads: none.
6. **Testing and release**: upload the .aab to a **Closed testing** track.

## The testing rule for new personal accounts

For personal developer accounts created after 13 November 2023, Google requires a **closed test with at least 12 testers who stay opted in for 14 days in a row** before you can apply for production access. Use real Google accounts on real devices (friends and family are fine). After 14 days, use **Apply for production** in Play Console. Review can take several days. Organization accounts do not have this rule.

## Updating later

Change the website and run `npx firebase-tools deploy`: the app shows the new version, no new Play upload needed. Only changes to the Android wrapper (name, icon, package settings) need a new .aab.

## Things to know

- The Play app is the web version in a full-screen wrapper. Reminders use Android notifications through Chrome and are not guaranteed to fire when the phone is idle. A native Android build would be needed for exact background alarms.
- Google can change Play requirements. Check the Play Console messages before you submit.
