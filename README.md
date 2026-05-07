# Ankleen

Ankleen is a safe, non-destructive, one-click editor tool for Anki that automatically fixes AI-generated Markdown and converts `$ ... $` / `$$ ... $$` LaTeX delimiters into simple Unicode or Anki-compatible MathJax.

## Features
- **Markdown Cleanup:** Safely converts `**bold**`, `__bold__`, `~strikethrough~`, and `` `inline code` `` to standard Anki HTML tags.
- **LaTeX Math Fixes:** Replaces generic `$` delimiters with native Anki `\(` and `\[` syntax, or drops them entirely in favor of plain Unicode for simple probability/set formulas (e.g. `\cup` -> `∪`).
- **Visual Spacing:** Automatically normalizes spacing by replacing single line breaks with double line breaks (`<br><br>`) to prevent text clumping.
- **Preview & Undo:** Generates a visual HTML diff preview to confirm changes. If you make a mistake, simply click "Undo Fix" to restore the previous state of the fields.

## Installation
1. Go to the [Releases](#) tab (or download the `.ankiaddon` file directly).
2. Double-click the `ankleen.ankiaddon` file to install it into Anki.
3. Restart Anki.

## Usage
1. Open any note in the Anki Editor.
2. Click the **"Fix Formatting"** button in the top formatting toolbar.
3. Review the diff preview pop-up and click **Apply**.
4. If you want to revert the changes, click **"Undo Fix"**.

## Development
To build the add-on package locally from source:
1. Clone this repository.
2. Run the included `build.ps1` script (or manually zip the contents of the `src` directory into an `.ankiaddon` file).
3. The resulting `.ankiaddon` file will be generated in the root directory.
