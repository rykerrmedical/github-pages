# Reference Pages for references.rykerrmedical.com

These pages provide a better UX for accessing medical references, offering both original and archived versions.

## Features

- **Two viewing options**: Original source or Archive.org backup
- **Embedded viewing**: View content within your site using iframes
- **External links**: Open in new tab for full experience
- **Responsive design**: Works on mobile and desktop

## Installation

1. **Copy all .md files** to your Jekyll repository

2. **Ensure you have a layout** called `default` in `_layouts/default.html` that these pages can use. If you want a custom layout for reference pages, create `_layouts/reference.html` and update the layout in each file.

3. **Customize styling** (optional):
   - The CSS is embedded in each page
   - You can move it to your main stylesheet
   - Adjust colors to match your brand

4. **Commit and push** to GitHub

## How It Works

Each page:
1. Shows two cards with options to view original or archived version
2. Provides buttons to open in new tab or view embedded
3. Uses iframe to display content within your site
4. Automatically generates Archive.org URLs

## Customization

### Change Layout
Edit the `layout:` field in each .md file's front matter

### Modify Styling
The CSS is inline in each file - you can:
- Move it to your main stylesheet
- Create a separate reference.css file
- Customize colors, spacing, etc.

### Add More Options
You could add:
- Google Scholar search link
- Citation export
- Related references
- Comments section

Total references: 200
