package ch.unibe.inf.seg.gitanalyzerplus;

import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.ConflictingFileAnalyzer;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.conflictresolution.ConflictResolutionResult;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.ConflictingFile;
import ch.unibe.inf.seg.gitanalyzerplus.analyze.analyzer.conflictingfile.model.files.File;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

public class ConflictResolutionCli {

    private static final String USAGE = """
            Usage: java -jar conflict-resolution-analyzer.jar [--formatting] <unmerged-file> <merged-file>

            The unmerged file must use diff3 conflict markers:
            <<<<<<<, |||||||, =======, and >>>>>>>.
            """;

    public static void main(String[] args) {
        try {
            Arguments arguments = Arguments.parse(args);
            List<ConflictResolutionResult> results = analyze(arguments);
            System.out.println(toJsonArray(results));
        } catch (IllegalArgumentException e) {
            System.err.println(e.getMessage());
            System.err.println(USAGE);
            System.exit(2);
        } catch (Exception e) {
            System.err.println(e.getMessage());
            System.exit(1);
        }
    }

    private static List<ConflictResolutionResult> analyze(Arguments arguments) throws Exception {
        File unmergedFile = readFile(arguments.unmergedFile(), arguments.useFormatting());
        File mergedFile = readFile(arguments.mergedFile(), arguments.useFormatting());
        ConflictingFile conflictingFile = new ConflictingFile(
                mergedFile,
                unmergedFile,
                arguments.unmergedFile().getFileName().toString()
        );
        return new ConflictingFileAnalyzer(conflictingFile).analyze();
    }

    private static File readFile(Path path, boolean useFormatting) throws IOException {
        return new File(Files.readAllBytes(path), useFormatting);
    }

    private static String toJsonArray(List<ConflictResolutionResult> results) {
        StringBuilder json = new StringBuilder("[");
        for (int i = 0; i < results.size(); i++) {
            if (i > 0) {
                json.append(",");
            }
            json.append('"').append(results.get(i)).append('"');
        }
        json.append("]");
        return json.toString();
    }

    private record Arguments(boolean useFormatting, Path unmergedFile, Path mergedFile) {
        static Arguments parse(String[] args) {
            boolean useFormatting = false;
            int index = 0;

            if (args.length > 0 && args[0].equals("--formatting")) {
                useFormatting = true;
                index = 1;
            }

            if (args.length - index != 2) {
                throw new IllegalArgumentException("Expected exactly two file arguments.");
            }

            Path unmergedFile = Path.of(args[index]);
            Path mergedFile = Path.of(args[index + 1]);
            validateReadableFile(unmergedFile);
            validateReadableFile(mergedFile);
            return new Arguments(useFormatting, unmergedFile, mergedFile);
        }

        private static void validateReadableFile(Path path) {
            if (!Files.isRegularFile(path) || !Files.isReadable(path)) {
                throw new IllegalArgumentException("File is not readable: " + path);
            }
        }
    }
}
