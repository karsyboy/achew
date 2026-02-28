<script>
    import {session} from "../stores/session.js";
    import {queueAutomation} from "../stores/queueAutomation.js";
    import {jobQueue, startNextQueuedJob} from "../stores/jobQueue.js";

    import ArrowDown from "@lucide/svelte/icons/arrow-down";
    import ArrowUp from "@lucide/svelte/icons/arrow-up";
    import ListOrdered from "@lucide/svelte/icons/list-ordered";
    import Play from "@lucide/svelte/icons/play";
    import Trash2 from "@lucide/svelte/icons/trash-2";

    const setupSteps = new Set(["source_setup", "abs_setup", "local_setup", "llm_setup"]);

    function formatDuration(seconds) {
        if (!seconds) return "";

        const totalSeconds = Math.round(seconds);
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);

        if (hours > 0) {
            return `${hours}h ${minutes}m`;
        }

        if (minutes > 0) {
            return `${minutes}m`;
        }

        return `${totalSeconds}s`;
    }

    function formatStep(step) {
        if (!step) return "Idle";

        return step
            .split("_")
            .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
            .join(" ");
    }

    function formatSource(job) {
        if (job.source_type === "local") {
            switch (job.local_layout) {
                case "multi_file_grouped":
                    return "Local folder";
                case "multi_file_individual":
                    return "Local file";
                default:
                    return "Local file";
            }
        }

        return "Audiobookshelf";
    }

    function formatAutoAdvanceSeconds(seconds) {
        return `${seconds} second${seconds === 1 ? "" : "s"}`;
    }

    function handleAutoAdvanceDelayChange(event) {
        queueAutomation.setConfiguredDelay(event.currentTarget.value);
    }

    async function handleStartNext() {
        try {
            await startNextQueuedJob(session);
        } catch (error) {
            console.error("Failed to start queued job:", error);
        }
    }

    $: hasPendingJobs = $jobQueue.jobs.length > 0;
    $: queueBusy = Boolean($jobQueue.startingJobId);
    $: canStartNext =
        hasPendingJobs &&
        !queueBusy &&
        !$session.loading &&
        ["idle", "completed"].includes($session.step);
    $: currentJobVisible =
        hasPendingJobs &&
        !setupSteps.has($session.step) &&
        !["idle"].includes($session.step);
    $: activeJobTitle =
        $session.book?.media?.metadata?.title ||
        $session.itemId ||
        "Current audiobook";
    $: autoAdvanceMessage = (() => {
        if ($queueAutomation.active) {
            return `Auto-advancing queued steps every ${formatAutoAdvanceSeconds($queueAutomation.active_delay_seconds)} until review. Any interaction stops it.`;
        }

        if ($queueAutomation.stop_reason === "disabled") {
            return "Auto-advance is off for queued jobs. Use the workflow buttons manually.";
        }

        if ($queueAutomation.stop_reason === "interaction") {
            return "Auto-advance stopped after you interacted with the workflow.";
        }

        if ($queueAutomation.stop_reason === "reviewing") {
            return "Auto-advance stopped at review.";
        }

        if ($queueAutomation.stop_reason === "ai_cleanup_failed") {
            return "Auto-advance stopped because AI cleanup failed for the current queued job.";
        }

        return null;
    })();
</script>

<aside class="job-queue-panel">
    <div class="queue-header">
        <div class="queue-header-copy">
            <div class="queue-eyebrow">Batch Start</div>
            <h3>Queue</h3>
        </div>
        <div class="queue-count">
            <ListOrdered size="16"/>
            {$jobQueue.jobs.length}
        </div>
    </div>

    <p class="queue-description">
        Queue items now, then run them through the existing workflow one at a time.
    </p>

    {#if autoAdvanceMessage}
        <div class="queue-status-note">
            {autoAdvanceMessage}
        </div>
    {/if}

    {#if currentJobVisible}
        <div class="current-job-card">
            <div class="section-label">Current job</div>
            <div class="current-job-title">{activeJobTitle}</div>
            <div class="current-job-meta">{formatStep($session.step)}</div>
        </div>
    {/if}

    <div class="queue-actions">
        <label class="queue-setting" for="queue-auto-advance-delay">
            <span class="queue-setting-label">Auto-advance</span>
            <div class="queue-setting-input">
                <input
                        id="queue-auto-advance-delay"
                        class="queue-delay-input"
                        type="number"
                        min="0"
                        step="1"
                        value={$queueAutomation.configured_delay_seconds}
                        on:input={handleAutoAdvanceDelayChange}
                />
                <span class="queue-setting-unit">sec</span>
            </div>
            <span class="queue-setting-hint">0 turns it off</span>
        </label>

        <button
                class="btn btn-verify queue-start-btn"
                on:click={handleStartNext}
                disabled={!canStartNext}
        >
            {#if queueBusy}
                <span class="btn-spinner"></span>
                Starting...
            {:else}
                <Play size="14"/>
                Start Next
            {/if}
        </button>

        <button
                class="btn btn-outline btn-sm"
                on:click={() => jobQueue.clear()}
                disabled={!hasPendingJobs || queueBusy}
        >
            Clear
        </button>
    </div>

    {#if hasPendingJobs}
        <div class="queue-list">
            {#each $jobQueue.jobs as job, index (job.queue_id)}
                <article class:starting={job.queue_id === $jobQueue.startingJobId} class="queue-item">
                    <div class="queue-item-main">
                        <div class="queue-index">{index + 1}</div>
                        <div class="queue-copy">
                            <div class="queue-title">{job.title}</div>
                            {#if job.subtitle}
                                <div class="queue-subtitle">{job.subtitle}</div>
                            {/if}
                            <div class="queue-meta">
                                <span>{formatSource(job)}</span>
                                {#if job.file_count}
                                    <span>{job.file_count} file{job.file_count === 1 ? "" : "s"}</span>
                                {/if}
                                {#if job.duration}
                                    <span>{formatDuration(job.duration)}</span>
                                {/if}
                            </div>
                        </div>
                    </div>

                    <div class="queue-item-actions">
                        <button
                                class="icon-btn"
                                on:click={() => jobQueue.moveJob(job.queue_id, -1)}
                                disabled={queueBusy || index === 0}
                                aria-label={`Move ${job.title} up`}
                        >
                            <ArrowUp size="14"/>
                        </button>
                        <button
                                class="icon-btn"
                                on:click={() => jobQueue.moveJob(job.queue_id, 1)}
                                disabled={queueBusy || index === $jobQueue.jobs.length - 1}
                                aria-label={`Move ${job.title} down`}
                        >
                            <ArrowDown size="14"/>
                        </button>
                        <button
                                class="icon-btn danger"
                                on:click={() => jobQueue.removeJob(job.queue_id)}
                                disabled={queueBusy}
                                aria-label={`Remove ${job.title} from queue`}
                        >
                            <Trash2 size="14"/>
                        </button>
                    </div>
                </article>
            {/each}
        </div>
    {:else}
        <div class="queue-empty">
            Add books or local files from the start screen to build a queue.
        </div>
    {/if}
</aside>

<style>
    .job-queue-panel {
        position: sticky;
        top: 1.5rem;
        display: grid;
        gap: 1rem;
        padding: 1.1rem;
        border: 1px solid var(--border-color);
        border-radius: 16px;
        background: color-mix(in srgb, var(--bg-card) 94%, transparent);
        box-shadow: 0 16px 40px color-mix(in srgb, var(--shadow-color) 30%, transparent);
    }

    .queue-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 1rem;
    }

    .queue-header h3 {
        margin: 0.15rem 0 0 0;
    }

    .queue-eyebrow,
    .section-label {
        font-size: 0.72rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--text-secondary);
        font-weight: 700;
    }

    .queue-count {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.35rem 0.65rem;
        border-radius: 999px;
        background: color-mix(in srgb, var(--accent-1) 12%, transparent);
        color: var(--text-primary);
        font-size: 0.82rem;
        font-weight: 700;
        white-space: nowrap;
    }

    .queue-description {
        margin: 0;
        color: var(--text-secondary);
        font-size: 0.92rem;
    }

    .queue-status-note {
        padding: 0.75rem 0.85rem;
        border-radius: 12px;
        background: color-mix(in srgb, var(--accent-1) 10%, transparent);
        border: 1px solid color-mix(in srgb, var(--accent-1) 16%, transparent);
        color: var(--text-primary);
        font-size: 0.82rem;
    }

    .current-job-card {
        display: grid;
        gap: 0.35rem;
        padding: 0.9rem;
        border-radius: 12px;
        background: color-mix(in srgb, var(--accent-2) 10%, transparent);
        border: 1px solid color-mix(in srgb, var(--accent-2) 18%, transparent);
    }

    .current-job-title,
    .queue-title {
        font-weight: 600;
        color: var(--text-primary);
        word-break: break-word;
    }

    .current-job-meta,
    .queue-subtitle,
    .queue-meta {
        color: var(--text-secondary);
        font-size: 0.82rem;
    }

    .queue-actions {
        display: flex;
        gap: 0.65rem;
        align-items: center;
        flex-wrap: wrap;
    }

    .queue-setting {
        display: grid;
        gap: 0.3rem;
        min-width: 0;
        color: var(--text-primary);
    }

    .queue-setting-label {
        font-size: 0.74rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--text-secondary);
    }

    .queue-setting-input {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        min-width: 0;
    }

    .queue-delay-input {
        width: 4.75rem;
        padding: 0.45rem 0.55rem;
        border-radius: 10px;
        border: 1px solid var(--border-color);
        background: var(--bg-secondary);
        color: var(--text-primary);
        font: inherit;
    }

    .queue-delay-input:focus {
        outline: none;
        border-color: color-mix(in srgb, var(--accent-1) 45%, transparent);
        box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-1) 12%, transparent);
    }

    .queue-setting-unit,
    .queue-setting-hint {
        font-size: 0.78rem;
        color: var(--text-secondary);
    }

    .queue-start-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.45rem;
        flex: 1;
        min-width: 8.5rem;
    }

    .queue-list {
        display: grid;
        gap: 0.75rem;
    }

    .queue-item {
        display: grid;
        gap: 0.75rem;
        padding: 0.9rem;
        border-radius: 12px;
        border: 1px solid var(--border-color);
        background: color-mix(in srgb, var(--bg-secondary) 90%, transparent);
    }

    .queue-item.starting {
        border-color: color-mix(in srgb, var(--accent-1) 30%, transparent);
        background: color-mix(in srgb, var(--accent-1) 10%, transparent);
    }

    .queue-item-main {
        display: flex;
        gap: 0.75rem;
        align-items: flex-start;
    }

    .queue-index {
        min-width: 1.8rem;
        height: 1.8rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        background: var(--bg-tertiary);
        color: var(--text-primary);
        font-size: 0.78rem;
        font-weight: 700;
        flex-shrink: 0;
    }

    .queue-copy {
        min-width: 0;
        display: grid;
        gap: 0.3rem;
    }

    .queue-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 0.6rem;
    }

    .queue-item-actions {
        display: flex;
        gap: 0.45rem;
        justify-content: flex-end;
    }

    .icon-btn {
        width: 2rem;
        height: 2rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--border-color);
        border-radius: 10px;
        background: transparent;
        color: var(--text-primary);
        cursor: pointer;
        transition: all 0.15s ease;
    }

    .icon-btn:hover:not(:disabled) {
        background: var(--hover-bg);
        border-color: color-mix(in srgb, var(--accent-1) 35%, transparent);
    }

    .icon-btn.danger:hover:not(:disabled) {
        border-color: color-mix(in srgb, var(--danger) 45%, transparent);
        color: var(--danger);
    }

    .icon-btn:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }

    .queue-empty {
        padding: 1rem;
        border-radius: 12px;
        border: 1px dashed var(--border-color);
        color: var(--text-secondary);
        font-size: 0.92rem;
    }

    @media (max-width: 1024px) {
        .job-queue-panel {
            position: static;
        }

        .queue-setting {
            width: 100%;
        }
    }
</style>
