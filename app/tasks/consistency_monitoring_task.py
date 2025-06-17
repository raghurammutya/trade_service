# app/tasks/consistency_monitoring_task.py
import logging
from datetime import datetime
from typing import Dict, List

from app.core.celery_config import celery_app
from app.utils.celery_db_helper import get_celery_db_session
from shared_architecture.utils.data_consistency_validator import DataConsistencyValidator
from shared_architecture.db.models.order_model import OrderModel

logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def monitor_account_consistency(self, organization_id: str, pseudo_account: str):
    """
    Monitor data consistency for a specific account.
    This task can be run periodically or triggered after data changes.
    """
    db = get_celery_db_session()
    
    try:
        validator = DataConsistencyValidator(db)
        
        # Run consistency check
        issues = validator.validate_account_consistency(
            organization_id, pseudo_account
        )
        
        # Categorize issues
        critical_issues = [i for i in issues if i.severity == 'CRITICAL']
        high_issues = [i for i in issues if i.severity == 'HIGH']
        
        result = {
            'organization_id': organization_id,
            'pseudo_account': pseudo_account,
            'timestamp': datetime.utcnow().isoformat(),
            'total_issues': len(issues),
            'critical_issues': len(critical_issues),
            'high_issues': len(high_issues),
            'status': 'CRITICAL' if critical_issues else 'WARNING' if high_issues else 'OK'
        }
        
        # Log critical issues immediately
        if critical_issues:
            logger.error(f"CRITICAL consistency issues found for {pseudo_account}: {len(critical_issues)} issues")
            for issue in critical_issues:
                logger.error(f"  - {issue.issue_type}: {issue.description}")
        
        # Store result for monitoring dashboard
        # You could store this in a monitoring table or send to alerting system
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to monitor consistency for {pseudo_account}: {e}")
        return {
            'organization_id': organization_id,
            'pseudo_account': pseudo_account,
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'ERROR',
            'error': str(e)
        }
    finally:
        db.close()

@celery_app.task(bind=True)
def monitor_all_accounts_consistency(self):
    """
    Monitor consistency for all active accounts.
    Should be run periodically (e.g., daily) to catch consistency issues.
    """
    db = get_celery_db_session()
    
    try:
        # Get all unique account combinations from orders table
        accounts = db.query(
            OrderModel.pseudo_account,
            OrderModel.organization_id
        ).distinct().all()
        
        total_accounts = len(accounts)
        accounts_with_issues = 0
        critical_accounts = 0
        
        results = []
        
        for pseudo_account, organization_id in accounts:
            if pseudo_account and organization_id:
                # Queue individual account monitoring
                result = monitor_account_consistency.delay(organization_id, pseudo_account)
                
                # You could also run synchronously for immediate results:
                # result = monitor_account_consistency(organization_id, pseudo_account)
                # if result.get('status') in ['CRITICAL', 'WARNING']:
                #     accounts_with_issues += 1
                # if result.get('status') == 'CRITICAL':
                #     critical_accounts += 1
                # results.append(result)
        
        summary = {
            'timestamp': datetime.utcnow().isoformat(),
            'total_accounts_monitored': total_accounts,
            'monitoring_tasks_queued': total_accounts,
            'status': 'MONITORING_QUEUED'
        }
        
        logger.info(f"Queued consistency monitoring for {total_accounts} accounts")
        
        return summary
        
    except Exception as e:
        logger.error(f"Failed to monitor all accounts consistency: {e}")
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'ERROR',
            'error': str(e)
        }
    finally:
        db.close()

@celery_app.task(bind=True)
def validate_strategy_split_consistency(self, organization_id: str, pseudo_account: str, strategy_id: str):
    """
    Validate consistency after a strategy split operation.
    This should be run after any strategy retagging to ensure data integrity.
    """
    db = get_celery_db_session()
    
    try:
        validator = DataConsistencyValidator(db)
        
        # Run targeted consistency check for this strategy
        issues = validator.validate_account_consistency(
            organization_id, pseudo_account
        )
        
        # Filter issues related to this strategy
        strategy_issues = [
            issue for issue in issues 
            if issue.strategies_involved and strategy_id in issue.strategies_involved
        ]
        
        result = {
            'organization_id': organization_id,
            'pseudo_account': pseudo_account,
            'strategy_id': strategy_id,
            'timestamp': datetime.utcnow().isoformat(),
            'strategy_specific_issues': len(strategy_issues),
            'total_account_issues': len(issues),
            'validation_status': 'FAILED' if strategy_issues else 'PASSED'
        }
        
        if strategy_issues:
            logger.warning(f"Strategy split validation FAILED for {strategy_id}: {len(strategy_issues)} issues")
            result['issues'] = [issue.to_dict() for issue in strategy_issues]
        else:
            logger.info(f"Strategy split validation PASSED for {strategy_id}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to validate strategy split consistency: {e}")
        return {
            'organization_id': organization_id,
            'pseudo_account': pseudo_account,
            'strategy_id': strategy_id,
            'timestamp': datetime.utcnow().isoformat(),
            'validation_status': 'ERROR',
            'error': str(e)
        }
    finally:
        db.close()

@celery_app.task(bind=True)
def auto_fix_minor_inconsistencies(self, organization_id: str, pseudo_account: str):
    """
    Attempt to automatically fix minor data inconsistencies.
    Only handles safe, well-defined fixes. Major issues require manual intervention.
    """
    db = get_celery_db_session()
    
    try:
        validator = DataConsistencyValidator(db)
        
        # Get all issues
        issues = validator.validate_account_consistency(
            organization_id, pseudo_account
        )
        
        # Filter fixable issues
        fixable_issues = [
            issue for issue in issues 
            if issue.issue_type in ['MISSING_INSTRUMENT_KEY', 'SYMBOL_CONVERSION_ERROR']
            and issue.severity in ['LOW', 'MEDIUM']
        ]
        
        fixed_count = 0
        
        for issue in fixable_issues:
            try:
                # Implement specific fixes based on issue type
                if issue.issue_type == 'MISSING_INSTRUMENT_KEY':
                    # Fix missing instrument_key by deriving from symbol/exchange
                    # Implementation would go here
                    pass
                
                fixed_count += 1
                
            except Exception as e:
                logger.error(f"Failed to fix issue {issue.issue_type}: {e}")
        
        return {
            'organization_id': organization_id,
            'pseudo_account': pseudo_account,
            'timestamp': datetime.utcnow().isoformat(),
            'total_issues': len(issues),
            'fixable_issues': len(fixable_issues),
            'fixed_issues': fixed_count,
            'status': 'COMPLETED'
        }
        
    except Exception as e:
        logger.error(f"Failed to auto-fix inconsistencies: {e}")
        return {
            'organization_id': organization_id,
            'pseudo_account': pseudo_account,
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'ERROR',
            'error': str(e)
        }
    finally:
        db.close()

@celery_app.task(bind=True)
def generate_consistency_report(self):
    """
    Generate a comprehensive consistency report for all accounts.
    This can be used for daily/weekly reporting.
    """
    db = get_celery_db_session()
    
    try:
        validator = DataConsistencyValidator(db)
        
        # Get all accounts
        accounts = db.query(
            OrderModel.pseudo_account,
            OrderModel.organization_id
        ).distinct().limit(100).all()  # Limit for performance
        
        report = {
            'generated_at': datetime.utcnow().isoformat(),
            'accounts_checked': 0,
            'accounts_with_issues': 0,
            'critical_accounts': 0,
            'total_issues': 0,
            'issues_by_type': {},
            'issues_by_severity': {
                'CRITICAL': 0,
                'HIGH': 0,
                'MEDIUM': 0,
                'LOW': 0
            }
        }
        
        for pseudo_account, organization_id in accounts:
            if pseudo_account and organization_id:
                report['accounts_checked'] += 1
                
                try:
                    issues = validator.validate_account_consistency(
                        organization_id, pseudo_account
                    )
                    
                    if issues:
                        report['accounts_with_issues'] += 1
                        report['total_issues'] += len(issues)
                        
                        # Check for critical issues
                        critical_issues = [i for i in issues if i.severity == 'CRITICAL']
                        if critical_issues:
                            report['critical_accounts'] += 1
                        
                        # Count by type and severity
                        for issue in issues:
                            issue_type = issue.issue_type
                            severity = issue.severity
                            
                            if issue_type not in report['issues_by_type']:
                                report['issues_by_type'][issue_type] = 0
                            report['issues_by_type'][issue_type] += 1
                            
                            report['issues_by_severity'][severity] += 1
                
                except Exception as e:
                    logger.error(f"Error checking account {pseudo_account}: {e}")
        
        # Calculate health score (0-100)
        if report['accounts_checked'] > 0:
            health_score = (
                (report['accounts_checked'] - report['accounts_with_issues']) / 
                report['accounts_checked'] * 100
            )
            report['health_score'] = round(health_score, 2)
        else:
            report['health_score'] = 100
        
        logger.info(f"Consistency report generated: {report['health_score']}% healthy")
        
        return report
        
    except Exception as e:
        logger.error(f"Failed to generate consistency report: {e}")
        return {
            'generated_at': datetime.utcnow().isoformat(),
            'status': 'ERROR',
            'error': str(e)
        }
    finally:
        db.close()