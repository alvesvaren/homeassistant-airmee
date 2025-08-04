# Airmee for home assistant

Airmee integration for home assistant, allowing you to see the next package ETA, number of packages currently being delivered, and some metadata about the next package.

This is still a work in progress and hasn't been tested that thoroughly. It is mostly "vibe-coded" so not sure how well it follows best practices for HA.

It also uses reverse-engineered API endpoints without any public documentation so stuff might break if airmee changes their backend.

## Installation (using HACS)
1. Add `https://github.com/alvesvaren/homeassistant-airmee` as a custom repository
2. Search up airmee and install it
3. Restart home assistant
4. Go to integrations
5. Add the airmee integration
6. Follow the setup flow, entering your county code (for example 46 for sweden), and the rest of your phone number, omitting the leading 0)
7. Done! You should now be able to see the sensors
