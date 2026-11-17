# dashboard-default-feature

**Started:** 2026-11-17  
**Completed:** 2026-11-17  
**Cost:** $0.0000

## Summary

Added a per-project "Default Feature" setting to the dashboard. The project detail page now shows a dropdown below the Persona selector where you can pick any of the project's features (active ones listed first, inactive grouped separately). When set, the bot reads this value via the dashboard API before showing the feature gate, and auto-selects the named feature without prompting the user. If no default is configured the existing gate dropdown behavior is unchanged. Changes: ProjectUpdate model (backend), Project type (frontend types), ProjectDetail UI (new dropdown + assignDefaultFeature), get_project_default_feature client helper, and _process_prompt gate logic.
