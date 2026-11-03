# Venue QR codes

Owners and authorized staff can view and download a QR code from their venue dashboard. The code opens the venue's guest search page, where customers can request songs without an account.

Set `PUBLIC_BASE_URL` in `.env` to the HTTP or HTTPS origin guests can reach, including the port when needed. For example:

```text
PUBLIC_BASE_URL=http://192.168.1.10:8901
ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.10
```

Replace the example IP address with the address of the computer running the app. Do not include a path or credentials in `PUBLIC_BASE_URL`. `ALLOWED_HOSTS` is a comma-separated list of hostnames or IP addresses without ports. Recreate the web service after changing `.env` so it receives the new environment values.

For a phone to scan a code during local testing, the phone must be able to reach the computer over the network. `localhost` on the phone refers to the phone, not the computer. A firewall or network configuration may also affect connectivity.

Changing the public address or venue slug requires printing a new code.
