# Setting up sign-in, cloud sync and the phone app

Everything here is free at personal scale (Firebase "Spark" plan). You need a Google account.

## 1. Create the Firebase project

1. Go to <https://console.firebase.google.com> and click **Add project**. Name it (for example `my-streak`). You can turn Google Analytics off.
2. On the project home page click the **web icon `</>`** to register a web app. Any nickname is fine. Skip "Firebase Hosting" for now.
3. Firebase shows a block of code called `firebaseConfig`. Copy the values into **firebase-config.js** like this (replace the `null` line):

```js
window.FIREBASE_CONFIG = {
  apiKey: "...",
  authDomain: "my-streak.firebaseapp.com",
  projectId: "my-streak",
  appId: "..."
};
```

(These values identify your project. They are not secret. Your data is protected by the rules in step 4.)

## 2. Turn on sign-in methods

In the console open **Build > Authentication > Get started > Sign-in method** and enable:

- **Email/Password** (works with any email address).
- **Google**: click it, enable, choose a support email, save.
- **Microsoft** (Outlook, Hotmail, work accounts). This one needs a free Azure registration:
  1. Open <https://portal.azure.com> > **Microsoft Entra ID** > **App registrations** > **New registration**.
  2. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**.
  3. In Firebase, enable the Microsoft provider. It shows a **redirect URL** (ends in `/__/auth/handler`). Paste it as the **Web** redirect URI in Azure and register.
  4. In Azure, **Certificates & secrets > New client secret**. Copy the secret **Value**.
  5. Copy the app's **Application (client) ID** and the secret Value into the Firebase Microsoft provider and save.

If you do not want Microsoft, remove `'microsoft'` from `STREAK_PROVIDERS` in firebase-config.js.

## 3. Create the database

**Build > Firestore Database > Create database.** Choose a location near you and **production mode**.

## 4. Publish the security rules and the website

From the project folder (Node is already installed):

```
npx firebase-tools login
npx firebase-tools use --add          (pick your project)
npx firebase-tools deploy
```

This publishes **firestore.rules** (each person can only read and write their own saved habits) and puts the web version online at `https://YOUR-PROJECT.web.app`.

## 5. Install it on your Android phone (free)

1. Open `https://YOUR-PROJECT.web.app` in **Chrome** on the phone.
2. Menu (three dots) > **Install app** (or **Add to Home screen**).
3. Tap **Sign in** at the top and sign in. Use the same account on every device.

## 6. Desktop app

After filling in firebase-config.js, rebuild with `npm run dist`. The desktop app signs in with **email and password** (Google and Microsoft pop-ups only work in the web and phone version). Use the same email and password you created on the web version.

## How syncing works

- The app always works offline and saves on the device first.
- When signed in, every change is uploaded after a moment, and changes from your other devices appear automatically.
- If two devices changed things while offline, the **most recent save wins** for the whole data set.
- The first time you sign in on a device that already has habits, the app asks whether to keep this device's data or use the data saved in your account.
- Press **Delete account** in the account window to remove your saved data and login.

## Costs

Free: Firebase Spark plan (sign-in for up to 50,000 monthly users, Firestore 1 GiB, 50,000 reads and 20,000 writes a day, Hosting). A custom domain is optional (about 10 to 15 dollars a year). Free-plan limits can change, so check the Firebase pricing page.
