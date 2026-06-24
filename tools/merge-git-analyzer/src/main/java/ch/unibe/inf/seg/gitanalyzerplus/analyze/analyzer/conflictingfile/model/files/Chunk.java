package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution.ConflictResolutionResult;

import java.util.ArrayList;

public class Chunk extends ArrayList<Section> {

    public static final int CHUNK_OURS = 0;
    public static final int BETWEEN_OURS_BASE = 1;
    public static final int CHUNK_BASE = 2;
    public static final int BETWEEN_BASE_THEIRS = 3;
    public static final int CHUNK_THEIRS = 4;

    public Chunk() {
        super();
    }

    public ConflictResolutionResult getConflictResolutionResult() {
        assert this.size() == 5;

        if (this.get(BETWEEN_OURS_BASE).isUnmapped() || this.get(BETWEEN_BASE_THEIRS).isUnmapped()) {
            return ConflictResolutionResult.CHUNK_NONCANONICAL;
        }

        if (!this.get(CHUNK_OURS).isFound() && !this.get(CHUNK_BASE).isFound() && !this.get(CHUNK_THEIRS).isFound()) {
            if (this.get(CHUNK_OURS).isEmpty()) {
                if (this.get(CHUNK_BASE).isEmpty()) {
                    return ConflictResolutionResult.CHUNK_SEMICANONICAL_OURSBASE;
                } else {
                    return ConflictResolutionResult.CHUNK_CANONICAL_OURS;
                }
            }
            if (this.get(CHUNK_THEIRS).isEmpty()) {
                if (this.get(CHUNK_BASE).isEmpty()) {
                    return ConflictResolutionResult.CHUNK_SEMICANONICAL_BASETHEIRS;
                } else {
                    return ConflictResolutionResult.CHUNK_CANONICAL_THEIRS;
                }
            }
            if (this.get(CHUNK_BASE).isEmpty()) {
                return ConflictResolutionResult.CHUNK_CANONICAL_BASE;
            }
            return ConflictResolutionResult.CHUNK_SEMICANONICAL_EMPTY;
        }

        if (this.get(CHUNK_OURS).isFound() && this.get(CHUNK_BASE).isFound() && this.get(CHUNK_THEIRS).isFound()) {
            return ConflictResolutionResult.CHUNK_SEMICANONICAL_OURSBASETHEIRS;
        }

        if (this.get(CHUNK_OURS).isFound()) {
            if (this.get(CHUNK_BASE).isFound()) {
                return ConflictResolutionResult.CHUNK_SEMICANONICAL_OURSBASE;
            } else if (this.get(CHUNK_THEIRS).isFound()) {
                return ConflictResolutionResult.CHUNK_SEMICANONICAL_OURSTHEIRS;
            } else {
                return ConflictResolutionResult.CHUNK_CANONICAL_OURS;
            }
        }

        if (this.get(CHUNK_BASE).isFound()) {
            if (this.get(CHUNK_OURS).isFound()) {
                return ConflictResolutionResult.CHUNK_SEMICANONICAL_OURSBASE;
            } else if (this.get(CHUNK_THEIRS).isFound()) {
                return ConflictResolutionResult.CHUNK_SEMICANONICAL_BASETHEIRS;
            } else {
                return ConflictResolutionResult.CHUNK_CANONICAL_BASE;
            }
        }

        if (this.get(CHUNK_THEIRS).isFound()) {
            if (this.get(CHUNK_OURS).isFound()) {
                return ConflictResolutionResult.CHUNK_SEMICANONICAL_OURSTHEIRS;
            } else if (this.get(CHUNK_BASE).isFound()) {
                return ConflictResolutionResult.CHUNK_SEMICANONICAL_BASETHEIRS;
            } else {
                return ConflictResolutionResult.CHUNK_CANONICAL_THEIRS;
            }
        }

        return ConflictResolutionResult.UNKNOWN;
    }
}
