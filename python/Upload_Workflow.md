# Upload Workflow

Making the Upload with Authentication process easier with only Email & Password authentication.

## How to use

```bash
$ upload_with_authentication.py GoPro -e your@email.com -p Password
```

In the case of wrong password/email:

```bash
$ upload_with_authentication.py GoPro --email your@email.com --password Password
[ERROR] Please confirm your Mapillary email/password
--email: your@email.com
--password: Password
```

In case of no password is supplied

```bash
$ upload_with_authentication.py GoPro -e your@email.com
Please input [Password]: upload.py <path> -e your@email.com -p Password
```