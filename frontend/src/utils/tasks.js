/**
 * What a model can be assigned to do, named the way the app names it.
 *
 * ONE definition. This lived in three components, each with its own copy of the
 * same object, which is how `latex_writer` came to read "Writing" in one place
 * after the section had been renamed Scribe everywhere else.
 *
 * The keys are the `task_type` strings the backend routes on -- the same values
 * `KNOWN_TASKS` lists in domain/model_manager/registry.py. Only tasks something
 * actually calls with belong here: an assignable task nothing routes is a
 * promise the app cannot keep, and the user would reasonably conclude their
 * model was being ignored.
 *
 * `where` names the section the work is visible in, because "Analysis" on its
 * own does not tell a researcher which screen gets better if they assign a
 * bigger model to it.
 */
export const TASKS = {
  general: {
    label: 'General',
    where: 'the fallback for anything not listed below',
  },
  analysis: {
    label: 'Analysis',
    where: 'summaries, claims and themes in LitGraph',
  },
  gap_analysis: {
    label: 'Gap finding',
    where: 'research gaps in LitGraph',
  },
  latex_writer: {
    label: 'Scribe',
    where: 'drafting LaTeX',
  },
};

/** display name for a task_type, falling back to the raw key. */
export function taskLabel(task) {
  return TASKS[task]?.label || task;
}

/** where the work shows up, or empty when we have nothing useful to say. */
export function taskWhere(task) {
  return TASKS[task]?.where || '';
}
