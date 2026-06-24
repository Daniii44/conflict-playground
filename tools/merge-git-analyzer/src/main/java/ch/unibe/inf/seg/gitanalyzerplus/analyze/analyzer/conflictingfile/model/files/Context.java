package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution.ConflictResolutionResult;

public class Context extends SectionList {

    public static final int BEFORE_CONTEXT = 0;
    public static final int CONTEXT = 1;
    public static final int AFTER_CONTEXT = 2;

    public Context() {
        super();
    }

    public ConflictResolutionResult getConflictResolutionResult() {
        assert this.size() == 3;
        if (this.get(BEFORE_CONTEXT).isUnmapped() || this.get(AFTER_CONTEXT).isUnmapped()) {
            return ConflictResolutionResult.CONTEXT_CHANGED;
        }
        if (!this.get(CONTEXT).isFound()) {
            if (this.get(CONTEXT).isEmpty()) {
                return ConflictResolutionResult.CONTEXT_UNCHANGED;
            } else {
                return ConflictResolutionResult.CONTEXT_CHANGED;
            }
        } else {
            return ConflictResolutionResult.CONTEXT_UNCHANGED;
        }
    }
}
