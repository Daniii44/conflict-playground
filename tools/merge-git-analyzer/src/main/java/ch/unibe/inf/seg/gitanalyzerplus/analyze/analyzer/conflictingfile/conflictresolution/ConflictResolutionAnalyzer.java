package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.ConflictingFile;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.Chunk;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.File;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.Section;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.SectionType;

import java.util.ArrayList;

/**
 * Analyzes how the conflicting chunks within a conflicting file were resolved.
 * To this end, the unmerged file is divided into sections (contexts and chunks). Next, the merged file is traversed,
 * and it is determined whether the sections are found in said file in their entirety and without changes.
 */
public class ConflictResolutionAnalyzer {
    protected final File unmergedFile;
    protected final File mergedFile;
    protected SectionMapping sectionMapping;
    protected boolean hasSectionStructureChanged;
    protected ArrayList<ConflictResolutionResult> results;

    public ConflictResolutionAnalyzer(ConflictingFile conflictingFile) {
        this(conflictingFile.unmergedFile(), conflictingFile.mergedFile());
    }

    public ConflictResolutionAnalyzer(File unmergedFile, File mergedFile) {
        this.mergedFile = mergedFile;
        this.unmergedFile = unmergedFile;
        this.unmergedFile.getSections().removeIf(Section::isChunkDelimiter);
        this.results = new ArrayList<>();
    }

    public boolean hasSectionStructureChanged() {
        return this.hasSectionStructureChanged;
    }

    public ArrayList<ConflictResolutionResult> getResults() {
        return this.results;
    }

    /**
     * Run the analysis.
     *
     * @throws ConflictResolutionAnalyzerException Thrown if there is an error at some point in the analysis
     */
    public void analyze() throws ConflictResolutionAnalyzerException {
        try {
            // if the merged file was deleted, skip the analysis
            if (this.mergedFile.isEmpty()) {
                this.handleEmptyFile();
            } else {
                this.handleNonEmptyFile();
            }
            if (this.results.contains(ConflictResolutionResult.UNKNOWN)) {
                throw new ConflictResolutionAnalyzerException("UNKNOWN_CONFLICT_RESOLUTION_RESULT");
            }
        } catch (Exception e) {
            throw new ConflictResolutionAnalyzerException(e.getMessage());
        }
    }

    private void handleEmptyFile() {
        this.hasSectionStructureChanged = false;
        int i = 0;
        while (i < this.unmergedFile.getSections().size()) {
            if (this.unmergedFile.getSections().get(i).isContext()) {
                if (this.unmergedFile.getSections().get(i).isEmpty()) {
                    this.results.add(ConflictResolutionResult.CONTEXT_UNCHANGED);
                } else {
                    this.results.add(ConflictResolutionResult.CONTEXT_CHANGED);
                }
            } else if (this.unmergedFile.getSections().get(i).isChunk()) {
                Chunk chunk = new Chunk();

                chunk.add(this.unmergedFile.getSections().get(i));
                i++;
                chunk.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
                chunk.add(this.unmergedFile.getSections().get(i));
                chunk.add(new Section(-1, -1, 0, 0, SectionType.EMPTY));
                i++;
                chunk.add(this.unmergedFile.getSections().get(i));

                this.results.add(chunk.getConflictResolutionResult());
            }
            i++;
        }
    }

    private void handleNonEmptyFile() {
        this.sectionMapping = new SectionMapping(this.unmergedFile, this.mergedFile);
        this.sectionMapping.calculate();
        this.hasSectionStructureChanged = this.sectionMapping.hasSectionStructureChanged();
        this.results = this.sectionMapping.getResults();
    }

    public static class ConflictResolutionAnalyzerException extends Exception {

        public ConflictResolutionAnalyzerException(String message) {
            super(message);
        }
    }
}
