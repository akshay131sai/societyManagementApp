# NestFlow Demo Walkthrough

Oct 26, 2026

## Overview

NestFlow is a housing-society management platform. One login opens a different app depending on the role: a platform console for the NestFlow operator, and a society workspace for admins, residents and staff.

This guide walks a presenter through the demo environment, role by role, and says what each screen shows. It uses one demo society, **Demo Heights** (Pune), which has one account for every role.

- **Environment:** staging server, demo data only. Safe to click around, create and delete.
- **Sign-in mode:** development sign-in. The app checks the email only; any password is accepted.
- **Audience:** presenters, testers and stakeholders seeing NestFlow for the first time.

## Getting in

Signing in takes two steps: a site password that guards the whole demo server, then the NestFlow login screen.

1. **Open the demo address.** Current address: https://shown-heel-wagon-currency.trycloudflare.com. It is a temporary link and changes whenever the server's tunnel restarts; ask the server admin for the latest one if it stops loading.
2. **Pass the site gate.** The browser shows a pop-up asking for a username and password. Username: `nestflow`. The password is shared separately by the server admin and is not written in this document.
3. **The login screen loads.** On wide screens it is split in two: a NestFlow hero image on the left and the sign-in form on the right, headed *Welcome back · Sign in to your society account*.
4. **Read the yellow notice.** A *Development sign-in* banner explains that any registered email works and the password is ignored. This only appears on the demo server.
5. **Enter an email** from the Demo accounts table below. Leave the password empty or type anything; the field says *not required in dev mode*.
6. **Click Sign in.** The Super Admin lands on the platform console (`/admin/dashboard`). Every other role lands on the society workspace (`/app/dashboard`).

Once inside, every screen shares one layout: a sidebar menu on the left, and a top bar with the page path, search, the notification bell and your avatar. A yellow **DEV AUTH** badge in the top bar is a reminder that the demo sign-in is on. On phones the sidebar becomes a menu button, and residents get a bottom bar: Home · Bills · Visitors · Utilities · More.

To switch roles, sign out from the avatar menu and sign in with another email. To compare two roles side by side, use a second browser or a private window.

## Demo accounts

Nine accounts cover every role. All except the Super Admin belong to Demo Heights, and the password can be anything.

| Role | Email | What the role is for | Menu items |
| --- | --- | --- | --- |
| Super Admin | youngstoneai@gmail.com | Runs the NestFlow platform: societies, plans, subscriptions. Sees no society data. | 7 |
| Society Admin | society.admin@demo.nestflow.in | Full control of one society. | 22 |
| Flat Owner | owner@demo.nestflow.in | Resident of flat A-101: own bills, utilities, family, visitors. | 14 |
| Maintenance Admin | maintenance.admin@demo.nestflow.in | Runs maintenance staff and tasks; triages complaints. | 10 |
| Maintenance staff | maintenance@demo.nestflow.in | Field worker; sees and updates own tasks only. | 4 |
| Housekeeping Admin | housekeeping.admin@demo.nestflow.in | Runs housekeeping staff, schedules and attendance. | 8 |
| Housekeeper | housekeeper@demo.nestflow.in | Sees and updates own housekeeping tasks only. | 3 |
| Security Admin | security.admin@demo.nestflow.in | Runs guards and shifts; sees the full visitor log. | 11 |
| Security guard | security@demo.nestflow.in | Logs visitors, deliveries and vehicles at the gate. | 7 |

The menu is built from each role's permissions, so a page a role cannot use never appears in its sidebar. The counts above come from the live demo server.

## Super Admin: the platform console

Sign in as **youngstoneai@gmail.com**. The Super Admin runs NestFlow itself and can create and lock societies, but cannot see any society's residents, bills or visitors.

| Page | What it shows | What to demo |
| --- | --- | --- |
| Dashboard | *Platform overview*: totals for societies, active, provisioning, setup failed, locked or suspended; active subscriptions, plans and platform users; *Recently added societies*. | Point out Demo Heights in the recent list. |
| Societies | Every society on the platform. Each one has its own isolated database. | Open Demo Heights to see its contact details, database and subscription. |
| Societies › New society | A form for society details, the society administrator, and the plan. | Creating one builds a new database, sets up roles, and makes the admin's login ready in seconds. |
| Society detail | Contact, database, subscription; buttons to lock, unlock, archive or retry setup. | Lock blocks every user of that society at once; unlock restores access. Their data is untouched. |
| Subscription Plans | What a society can buy: Starter, Growth and Enterprise, with price and limits. | Editing a plan never changes the terms of subscriptions already sold. |
| Subscriptions | One society's billing term at a time; assign, extend or suspend. | New societies start on a trial automatically. |
| Platform Users | Every account that can sign in, across all societies. | Roles inside a society are managed by that society, not here. |
| Audit Logs | Every privileged platform action, with who did it. Entries are never edited or removed. | Show the entry for the Demo Heights setup. |
| Settings | Defaults for new societies, server health, and background jobs. | Read-only values from the server configuration. |

Tip: if you demo **Lock** on Demo Heights, unlock it straight away. Otherwise none of the other demo accounts can sign in.

## Society Admin: running the society

Sign in as **society.admin@demo.nestflow.in**. The Society Admin sees all 22 menu items and is the best account for a full product tour.

The **Dashboard** shows the society's name and status, its subscription and time zone, counts of flats and residents, and *Members by role*: how many people hold each role. Demo Heights starts with one building (Demo Tower), one flat (A-101), one resident and eight members.

| Area | Pages | What they show |
| --- | --- | --- |
| Property | Structure, Flats, Residents | Buildings, blocks and floors; every flat with its area and occupancy (bulk-create a whole block from a numbering pattern); who lives where, owners and tenants. |
| People | Users & Roles | Everyone who can sign in to the society and their roles. Adding a user here gives them a login immediately. |
| Billing | Bill Builder, Bills, Payments | Build the maintenance formula once (base amount, per-square-foot rate, water slabs, rebates); generate and publish bills; record payments. Published bills cannot be edited, only corrected with a credit note. |
| Utilities | Water, Electricity, Parking, Vehicles | Meter readings and society totals; parking slots and who holds them; registered vehicles per flat. |
| Operations | Complaints, Maintenance, Housekeeping, Security, Visitors | Resident tickets; recurring and one-off staff tasks; who is on the premises right now and the gate log. |
| Community | Notices, Amenities | Announcements to residents; bookable spaces such as the clubhouse, with free slots. |
| Insight | Reports | Society reports with date ranges and CSV export. |
| Setup | Appearance, Settings | The society's colours, logo and light/dark mode; society details and billing defaults. |

Good things to show:

1. **Appearance**: change the main colour, and every page in this society, for every user, recolours at once.
2. **Structure › Flats**: bulk-create flats for a block in one step.
3. **Users & Roles**: add a new person with a role, then sign in as them straight away.
4. **Bill Builder → Bills**: build a template, generate a bill for A-101, publish it, then sign in as the Flat Owner to see it arrive.

## Flat Owner: the resident's view

Sign in as **owner@demo.nestflow.in**, the owner of flat A-101. Everything a resident sees is limited to their own flat; no other flat's data is reachable.

The resident **Dashboard** is different from the admin one. It shows what the household owes and uses: *Recent bills*, *Recent payments*, *Paid this year*, a *Where it goes* breakdown of the latest bill, Water and Electricity usage, and counts of parking slots, vehicles and pets. On a fresh demo it shows empty states such as *No bills yet* until the Society Admin publishes a bill.

| Page | What the resident can do |
| --- | --- |
| Flats | See their own flat, A-101. |
| My Family | Add the people who live with them and choose, per person, how much of the flat each one can see. |
| Bills, Payments | Read published maintenance bills and payment history. |
| Water, Electricity | See their own meter readings and usage. |
| Parking, Vehicles, Pets | See allotted slots; register vehicles and pets for the flat. |
| Complaints | Raise a ticket and get a ticket number to quote to the office. |
| Visitors | Pre-approve a guest, delivery or cab, and answer the gate when someone arrives. |
| Notices, Amenities | Read society announcements; book the clubhouse or other spaces. |

Good things to show:

1. **Complaints**: raise a ticket here, then sign in as the Maintenance Admin and find it.
2. **Visitors**: pre-approve a delivery, then sign in as the Security guard and check it in without a call to the flat.
3. **My Family**: add a family member and give them limited access.

## Staff: Maintenance, Housekeeping and Security

Each staff team has an admin who plans the work and a worker who carries it out. Workers see only their own tasks; admins see the whole team, plus Structure, Flats, Users & Roles and Reports for their area. All staff land on the society Dashboard.

### Maintenance

| Account | Menu | What to show |
| --- | --- | --- |
| Maintenance Admin (maintenance.admin@demo.nestflow.in) | Dashboard, Structure, Flats, Users & Roles, Water, Electricity, Complaints, Maintenance, Notices, Reports | **Complaints**: the triage board, with Open, Overdue, Unassigned, Critical and *Past their target* counts and average resolution time; assign a ticket to staff. **Maintenance**: create a task or a schedule ("the lift is serviced monthly") that raises the task each time it comes round, with vendor and estimated cost; *Awaiting sign-off* and *Spend this month* totals. |
| Maintenance staff (maintenance@demo.nestflow.in) | Dashboard, Complaints, Maintenance, Notices | Open an assigned task, add a comment, record what was done and what it cost, and send it for sign-off. |

### Housekeeping

| Account | Menu | What to show |
| --- | --- | --- |
| Housekeeping Admin (housekeeping.admin@demo.nestflow.in) | Dashboard, Structure, Flats, Users & Roles, Complaints, Housekeeping, Notices, Reports | **Housekeeping** uses the same screen as Maintenance: recurring cleaning schedules, task assignment and sign-off. |
| Housekeeper (housekeeper@demo.nestflow.in) | Dashboard, Housekeeping, Notices | The shortest menu in the product: today's own tasks and notices. |

### Security

| Account | Menu | What to show |
| --- | --- | --- |
| Security Admin (security.admin@demo.nestflow.in) | Dashboard, Structure, Flats, Users & Roles, Parking, Vehicles, Complaints, Security, Visitors, Notices, Reports | **Security**: *Inside right now* (everyone checked in and not yet out), the *Gate log*, and the *Incident log* with severity and police reference. |
| Security guard (security@demo.nestflow.in) | Dashboard, Flats, Parking, Vehicles, Security, Visitors, Notices | **Visitors**: *Log a visitor at the gate* (who, which flat, vehicle). Pre-approved visitors go straight in; anyone else waits until someone in the flat says yes. Counts show *Waiting at the gate*, *Expected today* and *Entries today*. |

## Demo script and troubleshooting

The strongest demo follows one piece of work as it passes between people. Each step below is a separate sign-in; use two browser windows so the audience sees both sides.

| Story | Step 1 | Step 2 | Step 3 | Step 4 |
| --- | --- | --- | --- | --- |
| Complaint | Flat Owner raises a complaint | Maintenance Admin assigns it to staff | Maintenance staff does the work, logs the cost | Maintenance Admin signs it off |
| Visitor | Flat Owner pre-approves a delivery | Security guard checks it in at the gate | Security Admin sees it on the premises list | |
| Billing | Society Admin builds the bill template | Society Admin publishes the A-101 bill | Flat Owner sees it on the dashboard | |

A suggested running order:

1. **Super Admin**: platform overview, open Demo Heights, show its plan and audit log.
2. **Society Admin**: dashboard, Structure, Users & Roles, change the colour in Appearance.
3. **Billing story**: build a template, publish the A-101 bill, show it on the Flat Owner's dashboard.
4. **Complaint story**: Flat Owner → Maintenance Admin → Maintenance staff → sign-off.
5. **Visitor story**: Flat Owner pre-approves, the guard checks the visitor in, the Security Admin sees them inside.
6. **Close on the Housekeeper**: a three-item menu shows how tightly each role is scoped.

### Known limitations

- **Demo sign-in only.** Passwords are not checked; real sign-in arrives when Firebase is set up. The site-gate password is the only protection, so do not share it widely.
- **Temporary address.** The link changes whenever the server's tunnel restarts.
- **Adding a block (wing) fails** with *temporarily unavailable* until the latest fix is deployed. Use the default block in Demo Tower instead.
- **Starts nearly empty.** Bills, readings, complaints and visitors appear only after you create them during the demo.

### Troubleshooting

| Problem | What to do |
| --- | --- |
| Page does not load at all | The tunnel address has changed. Ask the server admin for the current link. |
| Browser keeps asking for a password | That is the site gate. Username `nestflow`; get the password from the server admin. |
| Login says the account is not found | Check the email against the Demo accounts table; there is no self sign-up. |
| Every Demo Heights account is blocked | The society was locked from the Super Admin console. Unlock it on its Society detail page. |
| A menu item is missing | Expected: menus follow each role's permissions. Sign in as a role that has it. |
