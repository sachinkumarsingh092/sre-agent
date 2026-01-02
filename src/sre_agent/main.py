"""Main entry point for SRE Agent MVP."""

import argparse
import sys

from .config import load_config, validate_connections
from .logging_config import setup_logging, log_step, log_success, log_error
from .agent import SREAgent, MitigationAgent


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="SRE Agent MVP - Kubernetes incident diagnosis and mitigation"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip connection validation on startup",
    )
    parser.add_argument(
        "--diagnosis-only",
        action="store_true",
        help="Run diagnosis only (no mitigation)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug logging",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (don't loop)",
    )
    parser.add_argument(
        "--exit-on-idle",
        type=int,
        default=0,
        metavar="N",
        help="Exit after N consecutive checks with no alerts (0 = never exit)",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Load configuration (fail-fast on errors)
    config = load_config(args.config)

    # Override logging level if verbose
    if args.verbose:
        config.logging.level = "DEBUG"

    # Setup logging
    logger = setup_logging(config.logging)

    log_step(logger, "SRE Agent MVP Starting", f"Config: {args.config}")

    # Validate connections unless skipped
    if not args.skip_validation:
        log_step(logger, "Validating Connections")
        validate_connections(config)
        log_success(logger, "All connections validated")
    else:
        logger.warning("Skipping connection validation")

    # Initialize agent
    log_step(logger, "Initializing Agent")
    
    if args.diagnosis_only:
        agent = SREAgent(config)
        logger.info("Mode: Diagnosis only")
    else:
        agent = MitigationAgent(config)
        logger.info("Mode: Full mitigation")
    
    logger.info(f"Output directory: {config.agent.output_directory}")
    logger.info(f"Max retries: {config.agent.max_retries}")
    logger.info(f"Namespace: {config.kubernetes.namespace}")

    log_success(logger, "Agent initialized")

    # Run agent
    if args.once:
        # Single run mode
        log_step(logger, "Running Agent (single run)")
        incident = agent.run()
        if incident:
            log_success(logger, f"Processed incident {incident.id}: {incident.status}")
        else:
            logger.info("No incidents to process")
    else:
        # Continuous mode
        log_step(logger, "Running Agent (continuous mode)")
        logger.info("Press Ctrl+C to stop")
        if args.exit_on_idle > 0:
            logger.info(f"Will exit after {args.exit_on_idle} consecutive idle checks")
        
        import time
        idle_count = 0
        try:
            while True:
                incident = agent.run()
                if incident:
                    log_success(logger, f"Processed incident {incident.id}: {incident.status}")
                    idle_count = 0  # Reset on activity
                else:
                    idle_count += 1
                    if args.exit_on_idle > 0 and idle_count >= args.exit_on_idle:
                        logger.info(f"No alerts for {idle_count} checks, exiting...")
                        break
                
                # Wait before next check
                logger.info(f"Waiting {config.agent.retry_sleep_seconds}s before next check...")
                time.sleep(config.agent.retry_sleep_seconds)
        except KeyboardInterrupt:
            logger.info("Agent stopped by user")

    return 0


if __name__ == "__main__":
    sys.exit(main())
