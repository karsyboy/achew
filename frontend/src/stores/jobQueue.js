import {get, writable} from 'svelte/store';
import {queueAutomation} from './queueAutomation.js';

const STORAGE_KEY = 'achew-job-queue-v1';

function normalizeString(value) {
    return typeof value === 'string' ? value.trim() : '';
}

function createQueueId() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }

    return `queue-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function persistQueueState(state) {
    if (typeof localStorage === 'undefined') {
        return;
    }

    const serialized = {
        jobs: state.jobs,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(serialized));
}

function loadQueueState() {
    if (typeof localStorage === 'undefined') {
        return {
            jobs: [],
            startingJobId: null,
        };
    }

    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (!raw) {
            return {
                jobs: [],
                startingJobId: null,
            };
        }

        const parsed = JSON.parse(raw);
        const jobs = Array.isArray(parsed.jobs) ? parsed.jobs : [];
        return {
            jobs: jobs
                .filter((job) => job && typeof job === 'object' && job.job_key)
                .map((job) => ({
                    ...job,
                    queue_id: job.queue_id || createQueueId(),
                })),
            startingJobId: null,
        };
    } catch (error) {
        console.error('Failed to restore queued jobs:', error);
        return {
            jobs: [],
            startingJobId: null,
        };
    }
}

export function buildABSJobKey(itemId) {
    return `abs:${normalizeString(itemId)}`;
}

export function buildLocalJobKey(localItemId, localLayout = 'single_file') {
    return `local:${normalizeString(localItemId)}:${normalizeString(localLayout) || 'single_file'}`;
}

export function createABSQueueJob({
    itemId,
    title,
    subtitle = '',
    duration = 0,
    coverUrl = null,
    fileCount = null,
}) {
    const normalizedItemId = normalizeString(itemId);

    return {
        queue_id: createQueueId(),
        job_key: buildABSJobKey(normalizedItemId),
        source_type: 'abs',
        item_id: normalizedItemId,
        local_item_id: '',
        local_layout: null,
        title: title || normalizedItemId || 'Untitled ABS job',
        subtitle,
        duration: Number(duration) || 0,
        cover_url: coverUrl,
        file_count: fileCount,
        added_at: new Date().toISOString(),
    };
}

export function createLocalQueueJob({
    localItemId,
    localLayout = 'single_file',
    title,
    subtitle = '',
    duration = 0,
    fileCount = null,
}) {
    const normalizedLocalItemId = normalizeString(localItemId);
    const normalizedLayout = normalizeString(localLayout) || 'single_file';

    return {
        queue_id: createQueueId(),
        job_key: buildLocalJobKey(normalizedLocalItemId, normalizedLayout),
        source_type: 'local',
        item_id: '',
        local_item_id: normalizedLocalItemId,
        local_layout: normalizedLayout,
        title: title || normalizedLocalItemId || 'Untitled local job',
        subtitle,
        duration: Number(duration) || 0,
        cover_url: null,
        file_count: fileCount,
        added_at: new Date().toISOString(),
    };
}

export function getQueuedJobPayload(job) {
    if (!job) {
        return null;
    }

    if (job.source_type === 'local') {
        return {
            source_type: 'local',
            local_item_id: job.local_item_id,
            local_layout: job.local_layout || 'single_file',
        };
    }

    return {
        source_type: 'abs',
        item_id: job.item_id,
    };
}

function createJobQueueStore() {
    const initialState = loadQueueState();
    const {subscribe, set, update} = writable(initialState);

    function updateQueue(mutator) {
        update((state) => {
            const nextState = mutator(state);
            persistQueueState(nextState);
            return nextState;
        });
    }

    return {
        subscribe,

        addJob(job) {
            if (!job?.job_key) {
                return false;
            }

            let added = false;
            updateQueue((state) => {
                if (state.jobs.some((queuedJob) => queuedJob.job_key === job.job_key)) {
                    return state;
                }

                added = true;
                return {
                    ...state,
                    jobs: [...state.jobs, job],
                };
            });

            return added;
        },

        removeJob(queueId) {
            updateQueue((state) => ({
                ...state,
                jobs: state.jobs.filter((job) => job.queue_id !== queueId),
            }));
        },

        moveJob(queueId, direction) {
            if (!direction) {
                return;
            }

            updateQueue((state) => {
                const currentIndex = state.jobs.findIndex((job) => job.queue_id === queueId);
                if (currentIndex < 0) {
                    return state;
                }

                const targetIndex = currentIndex + direction;
                if (targetIndex < 0 || targetIndex >= state.jobs.length) {
                    return state;
                }

                const jobs = [...state.jobs];
                const [job] = jobs.splice(currentIndex, 1);
                jobs.splice(targetIndex, 0, job);

                return {
                    ...state,
                    jobs,
                };
            });
        },

        clear() {
            set({
                jobs: [],
                startingJobId: null,
            });
            persistQueueState({
                jobs: [],
                startingJobId: null,
            });
        },

        setStarting(queueId) {
            update((state) => ({
                ...state,
                startingJobId: queueId,
            }));
        },

        clearStarting() {
            update((state) => ({
                ...state,
                startingJobId: null,
            }));
        },

        shift() {
            let nextJob = null;

            updateQueue((state) => {
                if (state.jobs.length === 0) {
                    return state;
                }

                [nextJob] = state.jobs;
                return {
                    ...state,
                    jobs: state.jobs.slice(1),
                };
            });

            return nextJob;
        },

        peek() {
            const state = get({subscribe});
            return state.jobs[0] || null;
        },
    };
}

export const jobQueue = createJobQueueStore();

export async function startNextQueuedJob(sessionStore) {
    const queueState = get(jobQueue);
    if (queueState.startingJobId || queueState.jobs.length === 0) {
        return false;
    }

    const sessionState = get(sessionStore);
    if (sessionState.loading) {
        return false;
    }

    if (!['idle', 'completed'].includes(sessionState.step)) {
        return false;
    }

    const nextJob = queueState.jobs[0];
    if (!nextJob) {
        return false;
    }

    jobQueue.setStarting(nextJob.queue_id);

    try {
        if (sessionState.step === 'completed') {
            await sessionStore.deleteSession();
        }

        await sessionStore.createSession(getQueuedJobPayload(nextJob));
        queueAutomation.start(nextJob.job_key);
        jobQueue.shift();
        return true;
    } catch (error) {
        queueAutomation.stop('start_failed');
        throw error;
    } finally {
        jobQueue.clearStarting();
    }
}
