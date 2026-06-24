package ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files;

import org.eclipse.jgit.diff.RawText;

import java.util.ArrayList;

/**
 * Represents a file handled by Git. There are two types: the unmerged one and the merged one.
 */
public class File {

    public static final String DELIMITER = "=======";
    public static final String OURS = "<<<<<<<";
    public static final String THEIRS = ">>>>>>>";
    public static final String BASE = "|||||||";

    protected SectionList sections;

    protected String[] content;

    public File(byte[] input, boolean useFormatting) {
        // aka whitespace normalization
        if (useFormatting) {
            this.content = parseInputWithFormatting(input);
        } else {
            this.content = parseInputWithoutFormatting(input);
        }
        this.sections = new SectionList();
    }

    public String[] getContent() {
        return this.content;
    }

    private String[] parseInputWithoutFormatting(byte[] input) {
        RawText rawText = new RawText(input);
        String[] content = new String[rawText.size()];
        for (int i = 0; i < rawText.size(); i++) {
            content[i] = rawText.getString(i).stripTrailing();
        }
        return content;
    }

    public String[] parseInputWithFormatting(byte[] input) {
        RawText rawText = new RawText(input);
        ArrayList<String> formattedStrings = new ArrayList<>();
        for (int i = 0; i < rawText.size(); i++) {
            String formattedString = rawText.getString(i).strip().replaceAll("\\s+", " ");
            if (!formattedString.isEmpty()) {
                formattedStrings.add(formattedString);
            }
        }
        String[] content = new String[formattedStrings.size()];
        content = formattedStrings.toArray(content);
        return content;
    }

    public boolean isEmpty() {
        return getLength() == 0;
    }

    public int getLength() {
        return this.content.length;
    }

    public int getLengthWithoutGitMergingMarkers() {
        int length = 0;
        for (Section section : this.sections) {
            length += section.length();
        }
        return length;
    }

    public SectionList getSections() {
        return this.sections;
    }

    /**
     * Set the section list of the unmerged file. This is done by traversing all lines and grouping them into sections
     * of various types which are then added to the section list.
     */
    public void calculateSections() {
        // initialize the list and starting index of the file content
        sections = new SectionList();
        int index = 0;

        // find and add all chunks and contexts to the section list
        boolean lastSectionIsChunk = false;
        while (index < this.content.length) {
            if (isOursMarker(this.content[index])) {
                // add an empty context between two adjacent chunks
                if (lastSectionIsChunk) {
                    this.sections.add(new Section(0, 0, index, index, SectionType.CONTEXT));
                }
                index = this.setChunk(index);
                lastSectionIsChunk = true;
            } else {
                index = this.setContext(index);
                lastSectionIsChunk = false;
            }
        }

        this.handleFirstAndLastContexts();
        this.setIndices();

    }

    private void handleFirstAndLastContexts() {

        // assert that there is at least one chunk
        assert this.sections.size() >= 3;

        // add an empty first context if missing
        if (!sections.get(0).isSectionType(SectionType.CONTEXT)) {
            sections.add(0, new Section(0, 0, SectionType.CONTEXT));
        }

        // add an empty last context if missing
        if (!sections.get(sections.size() - 1).isSectionType(SectionType.CONTEXT)) {
            sections.add(sections.size(), new Section(sections.get(sections.size() - 1).getEnd(), sections.get(sections.size() - 1).getEnd(), SectionType.CONTEXT));
        }
    }

    private void setIndices() {
        assert this.sections.size() % 4 == 1;

        int i = 0;
        int sectionIndex = 0;
        while (i < this.sections.size()) {
            if (i % 4 == 0) {
                sections.get(i).setStructureIndex(sectionIndex);
                sections.get(i).setIndex(i);
                assert this.sections.get(i).isContext();
            } else {
                assert i % 4 == 1;
                sections.get(i).setStructureIndex(sectionIndex);
                sections.get(i).setIndex(i);
                assert sections.get(i).isChunkOurs();
                i++;
                sections.get(i).setStructureIndex(sectionIndex);
                sections.get(i).setIndex(i);
                assert sections.get(i).isChunkBase();
                i++;
                sections.get(i).setStructureIndex(sectionIndex);
                sections.get(i).setIndex(i);
                assert sections.get(i).isChunkTheirs();
            }
            i++;
            sectionIndex++;
        }
    }

    /**
     * Adds a chunk to the section list. The lines of the file are traversed and whenever Git's merging markers are encountered,
     * a section denoting such markers is added. All lines in between are marked as sections denoting chunk parts.
     *
     * @param index the starting line index that marks the last line of the previous context
     * @return the current line index that marks the first line of the next context
     */
    private int setChunk(int index) {
        int start;

        // skip Git's merging marker 1
        index++;

        // add all lines up to the next merging marker as a chunk section
        start = index;
        while (index < content.length && !isBaseMarker(content[index])) {
            index++;
        }
        if (index == content.length) {
            throw new IllegalArgumentException("Missing diff3 base marker after ours section.");
        }
        sections.add(new Section(start, index, SectionType.CHUNK_OURS));

        // skip Git's merging marker 2
        index++;

        // add all lines up to the next merging marker as a chunk section
        start = index;
        while (index < content.length && !isDelimiterMarker(content[index])) {
            index++;
        }
        if (index == content.length) {
            throw new IllegalArgumentException("Missing conflict delimiter after base section.");
        }
        sections.add(new Section(start, index, SectionType.CHUNK_BASE));

        // skip Git's merging marker 3
        index++;

        // add all lines up to the next merging marker as a chunk section
        start = index;
        while (index < content.length && !isTheirsMarker(content[index])) {
            index++;
        }
        if (index == content.length) {
            throw new IllegalArgumentException("Missing theirs marker after theirs section.");
        }

        sections.add(new Section(start, index, SectionType.CHUNK_THEIRS));

        // skip Git's merging marker 4
        index++;

        return index;
    }

    /**
     * Adds a context to the section list. The lines of the file are traversed until one of Git's merging markers is encountered
     * or the end of the file is reached.
     *
     * @param index the starting line index that marks the first line of the context
     * @return index of the last line of the found context
     */
    private int setContext(int index) {
        int start = index;

        // add all lines up to the next merging marker as a context section
        while (index < content.length) {
                if (!isOursMarker(content[index])) {
                index++;
            } else {
                break;
            }
        }
        sections.add(new Section(start, index, SectionType.CONTEXT));

        return index;
    }

    private static boolean isOursMarker(String line) {
        return line.startsWith(OURS);
    }

    private static boolean isBaseMarker(String line) {
        return line.startsWith(BASE);
    }

    private static boolean isDelimiterMarker(String line) {
        return line.equals(DELIMITER);
    }

    private static boolean isTheirsMarker(String line) {
        return line.startsWith(THEIRS);
    }

    @Override
    public String toString() {
        StringBuilder stringBuilder = new StringBuilder();
        for (int i = 0; i < this.content.length; i++) {
            stringBuilder.append(this.content[i]);
            if (i < this.content.length - 1) {
                stringBuilder.append("\n");
            }
        }
        return stringBuilder.toString();
    }
}
