Here’s a clean package you can use for PR4.

PR description draft

Title
Improve SmartThings HDMI source naming and per-TV SmartThings wording

Summary
This PR improves Samsung TV source handling when SmartThings is enabled by using clearer SmartThings-derived HDMI labels and more reliable source mapping/selection. It also clarifies the setup wording so users understand that enabling SmartThings applies to the specific TV being configured.

What changed

Use SmartThings input source mappings to build clearer source labels
Improve source selection so friendly labels resolve back to the correct SmartThings source IDs
Keep non-SmartThings behavior unchanged by falling back to generic TV/HDMI entries
Clarify setup wording to indicate SmartThings is being enabled for the current TV, not globally for all TVs

Expected user-visible behavior

When SmartThings is disabled:

Source list remains generic, for example:
TV
HDMI
HDMI1
HDMI2
HDMI3
HDMI4
Existing non-SmartThings behavior continues unchanged

When SmartThings is enabled:

Source list uses friendlier SmartThings-based labels where available, for example:
TV
HDMI1 - PlayStation
HDMI2 - Sky Q
HDMI3 - Fire TV
Selecting a friendly label switches to the correct input
The current source shown in the UI reflects the friendly label

UX wording update

Change checkbox text from:
Enable SmartThings
To:
Enable SmartThings for this TV

This makes it clearer that the toggle applies to the TV currently being configured, even though the OAuth authorization is account-level.

Test coverage
Tested in four scenarios:

v1.3.0 with SmartThings disabled
v1.3.0 with SmartThings enabled
PR4 with SmartThings disabled
PR4 with SmartThings enabled

Observed results

No regression with SmartThings disabled
Friendlier HDMI/input labels with SmartThings enabled
Correct input switching using SmartThings-mapped labels
Clearer current-source display with SmartThings enabled

Evidence
Attach before/after screenshots for:

Source list with SmartThings disabled
Source list with SmartThings enabled
Selecting HDMI inputs
Current source shown after selection
Setup wording before/after
Suggested wording patch in setup.py

These are the text changes I’d recommend.

Discovery flow additional field

Change:

"label": {"en": "Authorize SmartThings"},

to:

"label": {"en": "Enable SmartThings for this TV"},

And change the explanatory text from:

"Enable SmartThings for advanced features like input source control. "
"Check the box below to set up OAuth after selecting your TV."

to:

"Enable SmartThings for this TV for advanced features like input source control. "
"Check the box below to authorize your SmartThings account after selecting this TV."
Optional SmartThings setup screen

Change:

"label": {"en": "Enable SmartThings"},

to:

"label": {"en": "Enable SmartThings for this TV"},

And change the description from:

"Enable SmartThings for features like HDMI input switching and improved power management.\n\n"
"Click 'Skip' to complete setup without SmartThings, or check the box below to authorize."

to:

"Enable SmartThings for this TV for features like HDMI input switching and improved power management.\n\n"
"Click 'Skip' to complete setup without SmartThings for this TV, or check the box below to authorize your SmartThings account."
Manual entry form / discovery screen intro

Where you currently have:

"SmartThings OAuth (Optional)"

I would consider:

"SmartThings for this TV (Optional)"

That is clearer, though this one is slightly more optional than the checkbox-label change.

OAuth screen title

Current:

{"en": "SmartThings OAuth Authorization"}

Suggested:

{"en": "Authorize SmartThings Account"}

That makes the distinction clearer:

checkbox = per TV
authorization = account-level
What I would actually change for PR4

At minimum:

Enable SmartThings → Enable SmartThings for this TV
Authorize SmartThings → Enable SmartThings for this TV
OAuth screen title → Authorize SmartThings Account

That gives clarity without redesigning the flow.

Live test checklist

You can use this as your runbook.

Test environment notes

Record these once:

TV model:
Integration version under test:
SmartThings enabled: Yes / No
Named HDMI inputs configured on TV:
Remote/app version:
Date/time:
Phase A — Version 1.3.0, SmartThings disabled
Confirm integration is running v1.3.0
Configure TV without SmartThings
Open device/remote screen
Open source list
Capture screenshot: source list
Select HDMI1
Confirm TV switches
Capture screenshot: remote after selection
Capture screenshot/photo: TV screen or source banner
Select HDMI2
Confirm TV switches
Capture screenshot: remote after selection
Capture screenshot/photo: TV screen or source banner
Select TV
Confirm TV switches
Capture screenshot: remote after selection
Note whether any app/source entity is empty or confusing
Phase B — Version 1.3.0, SmartThings enabled
Reconfigure with SmartThings enabled
Capture screenshot: SmartThings enable wording in setup
Capture screenshot: OAuth/authorization screen
Open source list
Capture screenshot: source list
Note current source shown
Select each available named HDMI source
Confirm TV switches correctly
Capture screenshot: remote after selection
Capture screenshot/photo: TV screen or source banner
Manually change source on TV with TV remote
Wait for update/poll
Capture screenshot: remote reflects current source
Note duplicates, odd labels, or missing friendly names
Phase C — PR4, SmartThings disabled
Deploy/install PR4
Configure TV without SmartThings
Capture screenshot: setup wording
Open source list
Capture screenshot: source list
Repeat HDMI1 / HDMI2 / TV switching tests
Capture remote and TV-result screenshots
Confirm behavior matches or exceeds v1.3.0
Note regressions: yes/no
Phase D — PR4, SmartThings enabled
Configure TV with SmartThings enabled
Capture screenshot: setup wording
Capture screenshot: OAuth/authorization screen
Open source list
Capture screenshot: source list
Confirm friendly labels appear
Select each friendly HDMI label
Confirm TV switches correctly
Capture screenshot: remote after selection
Capture screenshot/photo: TV screen or source banner
Manually change source on TV
Confirm remote updates to friendly current source
Capture screenshot: current source shown
Check for duplicates
Check app list entity behavior
Note regressions: yes/no
Screenshot checklist

Use a consistent naming scheme.

v1.3.0 / SmartThings off
01-v130-stoff-setup.png
02-v130-stoff-source-list.png
03-v130-stoff-hdmi1-remote.png
04-v130-stoff-hdmi1-tv.jpg
05-v130-stoff-hdmi2-remote.png
06-v130-stoff-hdmi2-tv.jpg
07-v130-stoff-tv-remote.png
v1.3.0 / SmartThings on
11-v130-ston-setup.png
12-v130-ston-oauth.png
13-v130-ston-source-list.png
14-v130-ston-hdmi1-remote.png
15-v130-ston-hdmi1-tv.jpg
16-v130-ston-hdmi2-remote.png
17-v130-ston-hdmi2-tv.jpg
18-v130-ston-current-source.png
PR4 / SmartThings off
21-pr4-stoff-setup.png
22-pr4-stoff-source-list.png
23-pr4-stoff-hdmi1-remote.png
24-pr4-stoff-hdmi1-tv.jpg
25-pr4-stoff-hdmi2-remote.png
26-pr4-stoff-hdmi2-tv.jpg
27-pr4-stoff-tv-remote.png
PR4 / SmartThings on
31-pr4-ston-setup.png
32-pr4-ston-oauth.png
33-pr4-ston-source-list.png
34-pr4-ston-hdmi1-remote.png
35-pr4-ston-hdmi1-tv.jpg
36-pr4-ston-hdmi2-remote.png
37-pr4-ston-hdmi2-tv.jpg
38-pr4-ston-current-source.png
Short evidence summary template

You can paste this into the PR after testing.

Test summary

Tested against the same TV on v1.3.0 and PR4
Tested with SmartThings disabled and enabled
No regressions observed with SmartThings disabled
With SmartThings enabled, PR4 provided clearer HDMI/input labels and more intuitive current-source feedback

Key differences observed

v1.3.0:
[fill in]
PR4:
[fill in]

Examples

v1.3.0 source list:
[fill in]
PR4 source list:
[fill in]

Setup wording

Updated wording makes it clearer that SmartThings is being enabled for the currently configured TV, while account authorization remains a separate step

If you want, I can turn the wording patch into exact search-and-replace edits once you paste the relevant setup.py snippets.