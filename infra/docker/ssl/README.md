# TLS Certificate Setup

Place your TLS certificates in this directory:

- `fullchain.pem` - Full certificate chain (server cert + intermediates)
- `privkey.pem` - Private key

## Option 1: Let's Encrypt (Recommended for Production)

```bash
# Install certbot
sudo apt install certbot

# Get certificate (standalone mode)
sudo certbot certonly --standalone -d yourdomain.com

# Copy certificates
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ./fullchain.pem
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ./privkey.pem
sudo chmod 644 fullchain.pem privkey.pem
```

## Option 2: Self-Signed (Development/Testing Only)

```bash
# Generate self-signed certificate
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout privkey.pem \
  -out fullchain.pem \
  -subj "/CN=localhost"
```

## Option 3: Commercial Certificate

Follow your certificate provider's instructions to obtain:
1. Your server certificate
2. Intermediate certificate(s)
3. Your private key

Concatenate them into the required files:
```bash
cat server.crt intermediate.crt > fullchain.pem
cp server.key privkey.pem
```

## File Permissions

Ensure proper permissions:
```bash
chmod 644 fullchain.pem
chmod 600 privkey.pem
```

## Automatic Renewal (Let's Encrypt)

Add to crontab for automatic renewal:
```bash
0 0 1 * * certbot renew --quiet && docker-compose restart nginx
```
