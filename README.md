# TimeProof

TimeProof shows who rewrites history on Wikipedia, when and how, and only publishes what it can prove.
Junction 2026, team ENLMe. Data: 862,076 revisions of 19,742 articles of the Finnish Wikipedia on Finnish history.

- Docs: [`docs/`](docs/) (summary, Saturday plan, technical reference, team rules)
- Run locally: `cp .env.example .env`, fill in the passwords, then `docker compose up --build`
  (site and API on http://localhost:8000).

## Credits

- The versioned `article` table follows the official example
  [mariadb-system-versioning-wikipedia](https://github.com/MariaDB/mariadb-system-versioning-wikipedia) (MIT).
- Data: [mariadb-wikipedia-datasets](https://github.com/MariaDB/mariadb-wikipedia-datasets).
  Wikipedia text is under CC BY-SA 4.0.
