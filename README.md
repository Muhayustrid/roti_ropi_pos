### Roti Ropi Pos

Mobile POS backend integration for ERPNext

### Requirements

- Frappe/ERPNext v16 with `bakery_manufacturing` installed.
- **POS Settings > Invoice Type** set to **POS Invoice**.
- Dedicated cashier users with only the `Mobile POS Cashier` application role.
- Public OAuth Client configured for Authorization Code, response Code, token endpoint authentication method `None`, scope `all`, `skip_authorization = 0`, allowed role `Mobile POS Cashier`, and an approved redirect URI.
- OAuth Client ID stored per site:

```bash
bench --site <site> set-config mobile_pos_oauth_client_id <client-id>
```

Mobile clients must use PKCE S256. Do not issue or embed a client secret, API key, shared cashier credential, or Administrator credential.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-16
bench install-app roti_ropi_pos
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/roti_ropi_pos
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
