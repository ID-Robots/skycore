# Skycore Tests

This directory contains tests for the Skycore project.

## Test Structure

The tests are organized into two categories:

### 1. Bash Script Tests

Traditional bash script tests in files named `test_*.sh`. These tests use a simple framework defined in `run_tests.sh`.

Current test files:

- `test_install.sh` - Tests for the installation process

### 2. Bats Tests

Tests written using the [Bats](https://github.com/bats-core/bats-core) framework in files named `*.bats`. Bats provides a more robust testing framework specifically designed for Bash.

Current Bats test files:

- `banner.bats` - Tests for the print_banner function

## Running Tests

### Running All Tests

To run all tests (both Bash script tests and Bats tests):

```bash
./installer/sc.sh test
```

This will:

1. Run the standard bash script tests
2. Run the Bats tests if Bats is installed (and install it if needed)

### Running Just Bash Script Tests

```bash
cd tests
./run_tests.sh
```

### Running Just Bats Tests

```bash
cd tests
./run_bats_tests.sh
```

This will install Bats if needed and run all `.bats` test files.

### Running a Specific Bats Test

If you have Bats installed:

```bash
cd tests
bats banner.bats
```

## Adding New Tests

### Adding a New Bash Script Test

1. Create a new file named `test_FEATURE.sh` in the tests directory
2. Follow the pattern in existing test files

### Adding a New Bats Test

1. Create a new file named `FEATURE.bats` in the tests directory
2. Follow the pattern in existing bats files
3. Use the Bats syntax for test cases:

```bash
@test "Description of test" {
  # Test code here
  run some_command
  [ "$status" -eq 0 ]
  [ "$output" = "expected output" ]
}
```

## Test Migration

Tests are gradually being migrated from bash script tests to Bats tests. The list of migrated tests is maintained in `run_tests.sh`.
