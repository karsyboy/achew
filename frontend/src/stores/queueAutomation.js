import {writable} from 'svelte/store';

const STORAGE_KEY = 'achew-queue-automation-v1';

export const DEFAULT_QUEUE_AUTO_ADVANCE_SECONDS = 5;

export const QUEUE_AUTO_ADVANCE_STEPS = new Set([
    'select_cue_source',
    'cue_set_selection',
    'configure_asr',
    'chapter_editing',
]);

function normalizeAutoAdvanceSeconds(
    value,
    fallback = DEFAULT_QUEUE_AUTO_ADVANCE_SECONDS,
) {
    if (value === null || value === undefined) {
        return fallback;
    }

    if (typeof value === 'string' && value.trim() === '') {
        return fallback;
    }

    const parsedValue = Number(value);

    if (!Number.isFinite(parsedValue)) {
        return fallback;
    }

    return Math.max(0, Math.trunc(parsedValue));
}

function loadConfiguredDelaySeconds() {
    if (typeof localStorage === 'undefined') {
        return DEFAULT_QUEUE_AUTO_ADVANCE_SECONDS;
    }

    try {
        const rawValue = localStorage.getItem(STORAGE_KEY);
        if (rawValue === null) {
            return DEFAULT_QUEUE_AUTO_ADVANCE_SECONDS;
        }

        return normalizeAutoAdvanceSeconds(rawValue);
    } catch (error) {
        console.error('Failed to restore queue automation settings:', error);
        return DEFAULT_QUEUE_AUTO_ADVANCE_SECONDS;
    }
}

function persistConfiguredDelaySeconds(seconds) {
    if (typeof localStorage === 'undefined') {
        return;
    }

    localStorage.setItem(STORAGE_KEY, String(seconds));
}

function createQueueAutomationStore() {
    const configuredDelaySeconds = loadConfiguredDelaySeconds();
    const {subscribe, update} = writable({
        active: false,
        job_key: null,
        stop_reason: null,
        ai_cleanup_done: false,
        configured_delay_seconds: configuredDelaySeconds,
        active_delay_seconds: 0,
        active_delay_ms: 0,
    });

    return {
        subscribe,

        setConfiguredDelay(seconds) {
            update((state) => {
                const nextDelaySeconds = normalizeAutoAdvanceSeconds(
                    seconds,
                    state.configured_delay_seconds,
                );
                persistConfiguredDelaySeconds(nextDelaySeconds);

                return {
                    ...state,
                    configured_delay_seconds: nextDelaySeconds,
                };
            });
        },

        start(jobKey, delaySeconds = null) {
            update((state) => {
                const nextDelaySeconds = normalizeAutoAdvanceSeconds(
                    delaySeconds,
                    state.configured_delay_seconds,
                );

                return {
                    ...state,
                    active: nextDelaySeconds > 0,
                    job_key: nextDelaySeconds > 0 ? jobKey : null,
                    stop_reason: nextDelaySeconds > 0 ? null : 'disabled',
                    ai_cleanup_done: false,
                    active_delay_seconds: nextDelaySeconds,
                    active_delay_ms: nextDelaySeconds * 1000,
                };
            });
        },

        stop(reason = null) {
            update((state) => {
                if (!state.active && !state.job_key && state.stop_reason === reason) {
                    return state;
                }

                return {
                    ...state,
                    active: false,
                    job_key: null,
                    stop_reason: reason,
                    ai_cleanup_done: false,
                    active_delay_seconds: 0,
                    active_delay_ms: 0,
                };
            });
        },

        stopForInteraction() {
            update((state) => {
                if (!state.active) {
                    return state;
                }

                return {
                    ...state,
                    active: false,
                    job_key: state.job_key,
                    stop_reason: 'interaction',
                    ai_cleanup_done: state.ai_cleanup_done,
                };
            });
        },

        markAICleanupDone() {
            update((state) => {
                if (state.ai_cleanup_done) {
                    return state;
                }

                return {
                    ...state,
                    ai_cleanup_done: true,
                };
            });
        },
    };
}

export const queueAutomation = createQueueAutomationStore();
