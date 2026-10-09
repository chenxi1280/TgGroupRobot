# Review Findings Closure Design

## Scope

Close the six confirmed review findings without altering unrelated behavior or discarding the existing uncommitted work.

## Runtime and leader ownership

The bot acquires the PostgreSQL leader lock before migration/schema readiness. Startup records each completed lifecycle transition immediately. Shutdown consumes that state and reverses only transitions that actually completed. The leader connection is monitored; losing it is a terminal ownership failure that wakes the runtime and triggers orderly shutdown. Advisory-lock statements end their implicit transactions so the lock connection is not left idle in transaction.

## Scheduler durability

Restoring persisted scheduler state is a startup requirement. A read failure aborts scheduler startup. When a task crosses the automatic-pause threshold, persisting that transition is required and failure is surfaced instead of presenting an in-memory-only pause as durable.

## Verification transaction

The challenge/token is committed before restricting a Telegram member or sending a prompt. Prompt outcome changes are committed immediately, so later welcome-message or outer-handler failures cannot erase the challenge needed to unlock the member.

## Regression compatibility

Request-scope caching retains explicit loader/checker injection at handler boundaries. Tests are updated only where the intended public contract changed: points are a side path and the verification menu now contains a prompt-failure policy row. Operational UI loading errors remain visible.

## Acceptance

- Partial startup always invokes the matching cleanup operations.
- Concurrent startup cannot migrate before ownership is established.
- Leader connection loss causes runtime shutdown.
- Scheduler state failures prevent unsafe execution.
- Verification challenge is durable before Telegram side effects.
- Full pytest and static checks pass.
