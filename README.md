# 🧹 Immich Duplicate Cleaner (english, french below)

Python script to intelligently detect and delete **duplicate photos/videos** on a [Immich](https://github.com/immich-app/immich) server, prioritizing heic (Apple) files over size.

---

## ✨ Main features

- 🔍 Automatic recovery of duplicates via the Immich API
- 📸 Intelligent file sorting by :
  1. **Date taken** (`exif.dateTimeOriginal`)
  2. **Preferred format** : `.heic` in priority
  3. **File's size** (we keep the largest)
  4. **Richness of EXIF metadata**
- 🧪 **Simulation mode** to test without deleting, useful for viewing logs
- 🗑️ Option to delete to the recycle bin or permanently
- 📄 Automatic logging to a `.log` file (optional)

---

## ⚙️ Prerequisites

- Immich server operational (self-hosted or public)
- A valid **API key**
- Python ≥ 3.7

---

## 📦 Installation

1. Clone the repository and enter the directory
2. Create a virtual environment:
   ```bash
   python -m venv .venv
   ```
3. Activate it (PowerShell on Windows):
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   On Linux/macOS:
   ```bash
   source .venv/bin/activate
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## ⚙️ Configuration

1. Copy the example env file and edit it:
   ```bash
   copy .env.example .env   # Windows
   cp .env.example .env    # Linux/macOS
   ```
2. Edit `.env` and set at least:
   - `IMMICH_SERVER` – your Immich server URL (e.g. `https://immich.example.com`)
   - `IMMICH_API_KEY` – your API key from Immich (Settings → API Keys)
   - `IMMICH_DRY_RUN` – `true` to simulate only (default), `false` to actually delete
   - `IMMICH_DEFINITELY` – `false` for recycle bin (default), `true` for permanent deletion
   - `IMMICH_ENABLE_LOG` – `true` or `false` for log file creation

Alternatively, set these as environment variables directly instead of using a `.env` file.

---

## 🚀 Usage

```bash
python immich_duplicates_en.py
```

For the French version:

```bash
python immich_duplicates_fr.py
```

**Tip:** Run with `IMMICH_DRY_RUN=true` (default) first to see what would be deleted without making any changes.

---

# 🧹 Nettoyeur de doublons Immich (français)

Script Python pour détecter et supprimer intelligemment les **doublons photos/vidéos** sur un serveur [Immich](https://github.com/immich-app/immich), en **donnant la priorité aux fichiers heic (Apple)** par rapport à la taille.

---

## ✨ Fonctionnalités principales

- 🔍 Récupération automatique des doublons via l’API Immich
- 📸 Tri intelligent des fichiers par :
  - **Date de capture** (`exif.dateTimeOriginal`)
  - **Format préféré** : `.heic` en priorité
  - **Taille du fichier** (on garde le plus lourd)
  - **Richesse des métadonnées EXIF**
- 🧪 **Mode simulation** pour tester sans supprimer, utile pour voir les logs
- 🗑️ Option de suppression dans la corbeille ou définitive
- 📄 Journalisation automatique dans un fichier `.log` (optionnelle)

---

## ⚙️ Pré-requis

- Serveur Immich opérationnel (auto-hébergé ou public)
- Une **clé API** valide
- Python ≥ 3.7

---

## 📦 Installation

1. Clonez le dépôt et entrez dans le répertoire
2. Créez un environnement virtuel :
   ```bash
   python -m venv .venv
   ```
3. Activez-le (PowerShell sur Windows) :
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
   Sur Linux/macOS :
   ```bash
   source .venv/bin/activate
   ```
4. Installez les dépendances :
   ```bash
   pip install -r requirements.txt
   ```

---

## ⚙️ Configuration

1. Copiez le fichier d'exemple et modifiez-le :
   ```bash
   copy .env.example .env   # Windows
   cp .env.example .env     # Linux/macOS
   ```
2. Éditez `.env` et configurez au minimum :
   - `IMMICH_SERVER` – l'URL de votre serveur Immich (ex. `https://immich.example.com`)
   - `IMMICH_API_KEY` – votre clé API (Paramètres → Clés API)
   - `IMMICH_DRY_RUN` – `true` pour simuler uniquement (par défaut), `false` pour supprimer réellement
   - `IMMICH_DEFINITELY` – `false` pour la corbeille (par défaut), `true` pour suppression définitive
   - `IMMICH_ENABLE_LOG` – `true` ou `false` pour la création du fichier log

Vous pouvez aussi définir ces variables d'environnement directement, sans fichier `.env`.

---

## 🚀 Utilisation

```bash
python immich_duplicates_fr.py
```

Pour la version anglaise :

```bash
python immich_duplicates_en.py
```

**Conseil :** Exécutez d'abord avec `IMMICH_DRY_RUN=true` (par défaut) pour voir ce qui serait supprimé sans modifier quoi que ce soit.
