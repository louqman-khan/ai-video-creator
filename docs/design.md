# Design plan (local first, before any hosting)

Goal: look and behave like the established tools in this category (Descript, Adobe Firefly video editor, VEED, Runway, Pika, HeyGen), not like a developer prototype.

## What the research showed
- **Editors keep everything on one screen** and let the user resize panels: Descript has a script editor, scene editor, timeline and sidebar with draggable borders; Adobe Firefly puts the media panel on the left, the viewer in the centre, tools on the right and the timeline along the bottom; Riverside lets the timeline collapse to give the preview room.
  ([Descript layout](https://help.descript.com/hc/en-us/articles/37508206076429-Manage-the-editor-layout-with-the-View-menu), [Descript editor](https://help.descript.com/hc/en-us/articles/37585546799757-The-editor-interface), [Firefly panels](https://helpx.adobe.com/firefly/web/firefly-video-editor/set-up-your-project/change-view-of-panels.html), [Riverside](https://gotranscript.com/public/how-to-customize-your-workspace-in-riverside-editor))
- **Project lists are card grids with preview thumbnails**, status and creation date, search and filters above the grid, and actions in a hover/overflow menu, so destructive actions are not the loudest thing on the card.
  ([VEED dashboard](https://support.veed.io/en/articles/11641509-how-veed-s-dashboard-works), [Vexub projects](https://vexub.com/blog/vexub-projects-dashboard-overview), [Pika](https://www.saasui.design/pattern/dashboard/pika), [Runway](https://www.saasui.design/pattern/dashboard/runway), [Descript](https://www.saasui.design/pattern/dashboard/descript))
- **AI video tools put the "create" action first** and show the decisions that matter (source, format, duration) as clear choices, not a long form.
  ([AI video app design](https://screensdesign.com/articles/ai-video-generator-app-design/))
- Not found: Kling, CapCut, Kapwing, Clipchamp specifics. Decisions for those follow the common patterns above.

## Decisions
1. **App shell:** slim left sidebar (logo, Projects, New project, Setup, Account), content to the right. The editor is full-screen with its own slim top bar and a back arrow (like Descript/Firefly).
2. **Editor workspace (one screen):** left icon rail + side panel (Scenes, Captions, Avatar, Export, Credits), centre stage with the preview on a dark canvas, timeline along the bottom, the inspector under the timeline. Panels scroll on their own; the page itself does not.
3. **Projects:** responsive card grid with a thumbnail (first scene's picture), status badge, format and date, search box, "New project" as the primary action, delete in an overflow menu.
4. **New project:** two big choice cards (Upload a recording / Type a script), a drag-and-drop upload area, format as visual choices, advanced options collapsed.
5. **Visual language:** one accent (indigo), neutral greys, 12 px radius, soft shadows, system font stack, dark mode that follows the system, clear focus rings, 8 px spacing scale. Urdu text uses `dir="auto"` and a Nastaliq font stack where installed.
6. **Later:** responsive/mobile layout, Urdu interface language, onboarding tour.

## Status
See the progress log in `ROADMAP.md`.

## Chosen direction: "frame." (from Lovable, 2026-11-19)
Palette (light / dark): primary #246B62 / #69C9B0, accent coral #E7745D / #F38A72, success #277A58 / #72C99A, warning #AB6C1B / #E4B35E, danger #C34F4F / #EF8585, info #3F7EAD / #82BBE7,
background #F5F7F5 / #13191A, surface #FFFFFF / #1A2222, raised #EDF1EF / #222C2C, border #D9E2DE / #35413F, text #1B2826 / #F3F7F4, muted #667470 / #9DACAA.
Type: Space Grotesk (display) + DM Sans (text) + Noto Nastaliq Urdu (Urdu); all bundled in `frontend/public/fonts` (SIL OFL; licence files alongside). Scale 4/8/12/16/24/32/48/64, radius 4-12, controls 28/36/40.
Timeline tints: teal = pictures, coral = captions, blue = voice-over. Applied in `frontend/src/theme.css`.
Layout ideas taken over: start cards on the projects page, new-project page with the main choices on the left and a settings panel (language, format, options, Create) on the right, sort and search above the grid.
Left for later: credits/plan card (only when plans exist), duration badges on cards, visual-style and stock-visual choices on the new-project page (need backend support), breadcrumb.
