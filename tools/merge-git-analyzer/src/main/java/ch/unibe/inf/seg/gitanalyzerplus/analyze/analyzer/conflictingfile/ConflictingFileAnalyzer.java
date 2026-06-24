package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution.ConflictResolutionAnalyzer;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution.ConflictResolutionResult;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.ConflictingFile;

import java.util.ArrayList;
import java.util.List;

public class ConflictingFileAnalyzer {
    private final ConflictingFile conflictingFile;

    public ConflictingFileAnalyzer(ConflictingFile conflictingFile) {
        this.conflictingFile = conflictingFile;
    }

    public List<ConflictResolutionResult> analyze() throws ConflictResolutionAnalyzer.ConflictResolutionAnalyzerException {
        ConflictResolutionAnalyzer conflictResolutionAnalyzer = new ConflictResolutionAnalyzer(this.conflictingFile);
        conflictResolutionAnalyzer.analyze();

        if (conflictResolutionAnalyzer.hasSectionStructureChanged()) {
            throw new ConflictResolutionAnalyzer.ConflictResolutionAnalyzerException("STRUCTURE_CHANGED");
        }

        ArrayList<ConflictResolutionResult> results = conflictResolutionAnalyzer.getResults();
        validateResults(results);
        return List.copyOf(results);
    }

    private static void validateResults(List<ConflictResolutionResult> results) throws ConflictResolutionAnalyzer.ConflictResolutionAnalyzerException {
        int contextCount = 0;
        int chunkCount = 0;

        for (ConflictResolutionResult result : results) {
            if (result == ConflictResolutionResult.CONTEXT_CHANGED || result == ConflictResolutionResult.CONTEXT_UNCHANGED) {
                contextCount++;
            } else if (result != ConflictResolutionResult.UNKNOWN) {
                chunkCount++;
            }
        }

        if (chunkCount == 0) {
            throw new ConflictResolutionAnalyzer.ConflictResolutionAnalyzerException("NO_CHUNKS_FOUND");
        }
        if (contextCount != chunkCount + 1) {
            throw new ConflictResolutionAnalyzer.ConflictResolutionAnalyzerException("INVALID_CHUNK_CONTEXT_COUNT");
        }
    }
}
